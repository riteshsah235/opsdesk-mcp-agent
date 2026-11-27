"""Generic MCP-over-HTTP client. Knows nothing about Ops Desk: it only speaks tools/list and tools/call."""
import json, select, subprocess, time, urllib.request

RELAY_TIMEOUT = 45  # seconds to wait for one relayed reply


class McpClient:
    def __init__(self, url=None, relay_cmd=None):
        """url: plain HTTP endpoint. relay_cmd: argv of a process that relays JSON lines to the
        gateway from inside a private network namespace (see contained.sh)."""
        self.url, self.sid, self._id, self.deadline = url, None, 0, None
        self.proc = subprocess.Popen(relay_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) if relay_cmd else None

    def close(self):
        if self.proc:
            try:
                self.proc.stdin.close(); self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()

    def _post(self, body, h):
        if self.proc:
            self.proc.stdin.write(json.dumps({"body": body, "sid": self.sid}) + "\n"); self.proc.stdin.flush()
            wait = RELAY_TIMEOUT if self.deadline is None else max(0.1, min(RELAY_TIMEOUT, self.deadline - time.monotonic()))
            ready, _, _ = select.select([self.proc.stdout], [], [], wait)
            if not ready:
                raise RuntimeError("gateway relay timed out after %ds" % wait)
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("gateway relay exited unexpectedly")
            out = json.loads(line)
            if "error" in out:
                raise RuntimeError(out["error"])
            self.sid = out.get("sid") or self.sid
            return out["data"]
        req = urllib.request.Request(self.url, json.dumps(body).encode(), h)
        with urllib.request.urlopen(req, timeout=20) as r:
            self.sid = r.headers.get("Mcp-Session-Id") or self.sid
            return r.read().decode()

    def _rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self._id += 1
            body["id"] = self._id
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        data = self._post(body, h)
        if notify or not data.strip():
            return None
        msg = json.loads(data)
        if "error" in msg:
            raise RuntimeError(msg["error"])
        return msg["result"]

    def connect(self):
        self._rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "opsdesk-agent", "version": "1.0"}})
        self._rpc("notifications/initialized", notify=True)

    def list_tools(self):
        return self._rpc("tools/list")["tools"]

    def call(self, name, arguments):
        res = self._rpc("tools/call", {"name": name, "arguments": arguments})
        sc = res.get("structuredContent")
        if sc is not None:
            return sc.get("value")
        return "".join(c.get("text", "") for c in res.get("content", []))

"""Generic MCP-over-HTTP client. Knows nothing about Ops Desk: it only speaks tools/list and tools/call."""
import json, urllib.request


class McpClient:
    def __init__(self, url):
        self.url, self.sid, self._id = url, None, 0

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
        req = urllib.request.Request(self.url, json.dumps(body).encode(), h)
        with urllib.request.urlopen(req, timeout=20) as r:
            self.sid = r.headers.get("Mcp-Session-Id") or self.sid
            data = r.read().decode()
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

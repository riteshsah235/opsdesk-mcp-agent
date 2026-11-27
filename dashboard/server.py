"""Local Ops Desk dashboard. Serves one page and a tiny JSON API on 127.0.0.1 only.

The server runs the same agent loop as the terminal demo against the same contained gateway.
The browser never talks to the gateway: it only receives a structured trace recorded at each real
MCP tool call. Nothing here defines a tool; tools are discovered from the gateway at run time."""
import json, os, re, secrets, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "agent"))
from agent import AgentError, MAX_TICKET_CHARS, groq_chat, parse_decision, redact, run_ticket
from demo import CASES, scripted_chat_for
from mcp_client import McpClient

HOST = "127.0.0.1"          # fixed on purpose: there is no option to listen elsewhere
MAX_BODY = 4096
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
ORDER_RE = re.compile(r"\bA\d{4}\b")


def scripted_for_ticket(ticket):
    """Offline stand-in for the model: pulls an order ID out of the ticket and echoes the backend's answer."""
    m = ORDER_RE.search(ticket)
    if m:
        return scripted_chat_for(m.group(0))
    return lambda messages, tools: {"role": "assistant", "content": "DECISION: INFO - the scripted model found no order ID (try A1001 to A1004)"}


def default_client():
    return McpClient(relay_cmd=["sh", os.path.join(HERE, "..", "agent", "contained.sh")])


class App:
    def __init__(self, client_factory=default_client, live_available=None):
        self.client_factory = client_factory
        self.live_available = bool(os.environ.get("GROQ_API_KEY", "").strip()) if live_available is None else live_available
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()   # one run at a time: each run starts its own contained gateway
        self.tools = []
        self.client = None

    def _client(self):
        """One contained gateway is kept for the life of the server, so runs do not pay its start-up time."""
        if self.client is None:
            c = self.client_factory()
            try:
                c.connect()
            except Exception:
                c.close()
                raise
            self.client = c
        return self.client

    def drop_client(self):
        c, self.client = self.client, None
        if c is not None:
            c.close()

    def discover(self):
        self.tools = [{"name": t["name"], "description": (t.get("description") or "")[:300]} for t in self._client().list_tools()]

    def run(self, ticket, mode):
        events = []
        chat = scripted_for_ticket(ticket) if mode == "scripted" else groq_chat
        t0 = time.perf_counter()
        try:
            kwargs = {"chat": chat} if mode == "scripted" else {}
            out = run_ticket(self._client(), ticket, log=lambda _l: None, trace=events.append, **kwargs)
        except (RuntimeError, OSError):
            self.drop_client()   # next run starts a fresh gateway
            raise
        d = parse_decision(out) or ("NO DECISION", "treat this ticket as NEEDS_HUMAN")
        return {"mode": mode, "decision": d[0], "reason": redact(d[1]), "trace": events, "final": redact(out),
                "total_ms": round((time.perf_counter() - t0) * 1000)}


def make_handler(app, port_getter):
    class H(BaseHTTPRequestHandler):
        server_version = "OpsDesk"
        def log_message(self, *a):
            pass

        def _origin_ok(self):
            port = port_getter()
            hosts = {"127.0.0.1:%d" % port, "localhost:%d" % port}
            if self.headers.get("Host", "") not in hosts:
                return False
            o = self.headers.get("Origin")
            return o is None or o in {"http://" + h for h in hosts}

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._origin_ok():
                return self._send(403, {"error": "forbidden host"})
            path = self.path.split("?", 1)[0]
            if path in STATIC:
                name, ctype = STATIC[path]
                with open(os.path.join(HERE, "static", name), "rb") as f:
                    body = f.read()
                if path == "/":
                    body = body.replace(b"__TOKEN__", app.token.encode())
                return self._send(200, body, ctype)
            if path == "/api/info":
                return self._send(200, {"tools": app.tools, "live_available": app.live_available, "max_ticket_chars": MAX_TICKET_CHARS,
                                        "cases": [{"order": o, "ticket": t, "expected": e, "note": n} for o, t, e, n in CASES]})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            if not self._origin_ok():
                return self._send(403, {"error": "forbidden host or origin"})
            if self.path.split("?", 1)[0] != "/api/run":
                return self._send(404, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Dashboard-Token", ""), app.token):
                return self._send(403, {"error": "bad token"})
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._send(415, {"error": "JSON only"})
            try:
                n = int(self.headers.get("Content-Length", "-1"))
            except ValueError:
                n = -1
            if n < 0 or n > MAX_BODY:
                return self._send(413, {"error": "request too large"})
            try:
                req = json.loads(self.rfile.read(n))
                ticket, mode = req["ticket"], req.get("mode", "scripted")
                if not isinstance(ticket, str) or mode not in ("live", "scripted"):
                    raise ValueError
            except (ValueError, KeyError, TypeError):
                return self._send(400, {"error": "expected JSON {ticket: string, mode: live|scripted}"})
            if mode == "live" and not app.live_available:
                return self._send(409, {"error": "Live mode needs GROQ_API_KEY in .env on the machine running the dashboard."})
            if not app.lock.acquire(blocking=False):
                return self._send(429, {"error": "A run is already in progress. Try again in a few seconds."})
            try:
                return self._send(200, app.run(ticket, mode))
            except AgentError as e:
                return self._send(422, {"error": redact(e)})
            except (RuntimeError, OSError, ValueError) as e:
                return self._send(502, {"error": "gateway or tool failure: " + redact(e)})
            except Exception:
                app.drop_client()
                return self._send(500, {"error": "internal error; see the server console"})
            finally:
                app.lock.release()
    return H


def serve(app, port=8765):
    holder = {}
    srv = ThreadingHTTPServer((HOST, port), make_handler(app, lambda: holder["port"]))
    holder["port"] = srv.server_address[1]
    return srv


def main():
    port = int(os.environ.get("PORT", "8765"))
    app = App()
    print("Checking the gateway ...", flush=True)
    try:
        app.discover()
    except (RuntimeError, OSError, ValueError) as e:
        print("ERROR: could not start the contained gateway: %s\nRun sh agent/preflight.sh for fixes." % redact(e), file=sys.stderr)
        return 3
    srv = serve(app, port)
    print("Tools from the gateway: " + ", ".join(t["name"] for t in app.tools))
    print("Ops Desk dashboard: http://127.0.0.1:%d  (this computer only; Ctrl+C to stop)" % srv.server_address[1])
    print("Live model: %s" % ("available" if app.live_available else "not available (no GROQ_API_KEY); scripted mode works"))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        app.drop_client()
    return 0


if __name__ == "__main__":
    sys.exit(main())

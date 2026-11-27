"""Dashboard tests. Boundary tests use a fake gateway client (no gateway needed).
With GG available the end-to-end test also runs the real contained gateway (scripted model, no key)."""
import http.client, json, os, socket, sys, threading, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import server


class FakeClient:
    def connect(self): pass
    def close(self): pass
    def list_tools(self):
        return [{"name": "get_order", "description": "d", "inputSchema": {"type": "object"}}, {"name": "evaluate_refund", "description": "d", "inputSchema": {"type": "object"}}]
    def call(self, name, args):
        return "A1002 | x" if name == "get_order" else "DENY: outside 30 day refund window"


def start(factory=FakeClient, live=False):
    app = server.App(client_factory=factory, live_available=live)
    app.discover()
    srv = server.serve(app, 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return app, srv, srv.server_address[1]


def req(port, method, path, body=None, headers=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    h = {"Host": host or "127.0.0.1:%d" % port}
    h.update(headers or {})
    c.request(method, path, body=body, headers=h)
    r = c.getresponse()
    data = r.read()
    return r.status, dict(r.getheaders()), data


class Boundaries(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.srv, cls.port = start()
        cls.ok = {"Content-Type": "application/json", "X-Dashboard-Token": cls.app.token}
        cls.body = json.dumps({"ticket": "Refund order A1002. Decide.", "mode": "scripted"})

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_listens_on_loopback_only(self):
        self.assertEqual(self.srv.server_address[0], "127.0.0.1")

    def test_page_and_security_headers(self):
        st, h, data = req(self.port, "GET", "/")
        self.assertEqual(st, 200)
        self.assertIn(self.app.token.encode(), data)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(h["Cache-Control"], "no-store")

    def test_wrong_host_rejected(self):  # DNS rebinding
        self.assertEqual(req(self.port, "GET", "/", host="evil.example:%d" % self.port)[0], 403)
        self.assertEqual(req(self.port, "GET", "/api/info", host="evil.example")[0], 403)

    def test_foreign_origin_rejected(self):
        st, _, _ = req(self.port, "POST", "/api/run", self.body, dict(self.ok, Origin="http://evil.example"))
        self.assertEqual(st, 403)

    def test_token_required(self):
        bad = dict(self.ok); bad["X-Dashboard-Token"] = "nope"
        self.assertEqual(req(self.port, "POST", "/api/run", self.body, bad)[0], 403)
        no = {"Content-Type": "application/json"}
        self.assertEqual(req(self.port, "POST", "/api/run", self.body, no)[0], 403)

    def test_json_only_and_size_cap(self):
        self.assertEqual(req(self.port, "POST", "/api/run", self.body, dict(self.ok, **{"Content-Type": "text/plain"}))[0], 415)
        big = json.dumps({"ticket": "x" * 9000, "mode": "scripted"})
        self.assertEqual(req(self.port, "POST", "/api/run", big, self.ok)[0], 413)

    def test_bad_requests(self):
        for body in ("not json", json.dumps({"ticket": 5}), json.dumps({"ticket": "a", "mode": "root"}), json.dumps({})):
            self.assertEqual(req(self.port, "POST", "/api/run", body, self.ok)[0], 400, body)

    def test_ticket_limits_and_secret_guard(self):
        long = json.dumps({"ticket": "x" * 2500, "mode": "scripted"})
        st, _, data = req(self.port, "POST", "/api/run", long, self.ok)
        self.assertEqual(st, 422)
        key = json.dumps({"ticket": "my key is gsk_" + "a" * 30, "mode": "scripted"})
        st, _, data = req(self.port, "POST", "/api/run", key, self.ok)
        self.assertEqual(st, 422)
        self.assertNotIn(b"gsk_aaaa", data)

    def test_live_refused_without_key(self):
        st, _, data = req(self.port, "POST", "/api/run", json.dumps({"ticket": "A1002", "mode": "live"}), self.ok)
        self.assertEqual(st, 409)
        self.assertNotIn(b"gsk_", data)

    def test_only_fixed_routes(self):
        for p in ("/mcp", "/GV", "/../server.py", "/static/app.js", "/%2e%2e/server.py", "/.env", "/api/run"):
            self.assertIn(req(self.port, "GET", p)[0], (404, 405, 501), p)
        self.assertEqual(req(self.port, "POST", "/mcp", "{}", self.ok)[0], 404)

    def test_info_exposes_no_secrets(self):
        st, _, data = req(self.port, "GET", "/api/info")
        info = json.loads(data)
        self.assertEqual(info["live_available"], False)
        self.assertEqual([t["name"] for t in info["tools"]], ["get_order", "evaluate_refund"])
        self.assertEqual(len(info["cases"]), 4)
        self.assertNotIn("GROQ", data.decode())

    def test_run_returns_recorded_trace(self):
        st, _, data = req(self.port, "POST", "/api/run", self.body, self.ok)
        r = json.loads(data)
        self.assertEqual(st, 200)
        self.assertEqual([t["name"] for t in r["trace"]], ["get_order", "evaluate_refund"])
        self.assertEqual(r["trace"][1]["args"], {"order_id": "A1002"})
        self.assertEqual((r["decision"], r["mode"]), ("DENY", "scripted"))

    def test_concurrent_run_refused(self):
        self.assertTrue(self.app.lock.acquire(blocking=False))
        try:
            self.assertEqual(req(self.port, "POST", "/api/run", self.body, self.ok)[0], 429)
        finally:
            self.app.lock.release()

    def test_scripted_free_text_without_order_id(self):
        body = json.dumps({"ticket": "Where is my parcel?", "mode": "scripted"})
        r = json.loads(req(self.port, "POST", "/api/run", body, self.ok)[2])
        self.assertEqual(r["decision"], "INFO")
        self.assertEqual(r["trace"], [])

    def test_gateway_failure_reported_and_recovers(self):
        class Boom(FakeClient):
            def call(self, n, a): raise RuntimeError("gateway relay exited unexpectedly")
        app, srv, port = start(Boom)
        try:
            h = {"Content-Type": "application/json", "X-Dashboard-Token": app.token}
            st, _, data = req(port, "POST", "/api/run", self.body, h)
            self.assertIn(st, (200, 502))
            self.assertNotIn(b"Traceback", data)
        finally:
            srv.shutdown()


@unittest.skipUnless(os.environ.get("GG") or __import__("shutil").which("gg"), "gg not available")
class EndToEnd(unittest.TestCase):
    def test_real_gateway_scripted_run(self):
        app = server.App(live_available=False)
        app.discover()
        srv = server.serve(app, 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        try:
            self.assertIn("evaluate_refund", [t["name"] for t in app.tools])
            h = {"Content-Type": "application/json", "X-Dashboard-Token": app.token}
            for order, exp in (("A1001", "APPROVE"), ("A1004", "NEEDS_HUMAN")):
                st, _, data = req(port, "POST", "/api/run", json.dumps({"ticket": "Refund order %s. Decide." % order, "mode": "scripted"}), h)
                r = json.loads(data)
                self.assertEqual((st, r["decision"]), (200, exp))
                self.assertEqual([t["name"] for t in r["trace"]], ["get_order", "evaluate_refund"])
            # the gateway is only reachable inside its private namespace
            for p in (18080, 18081):
                s = socket.socket(); s.settimeout(1)
                self.assertNotEqual(s.connect_ex(("127.0.0.1", p)), 0, "gateway port %d reachable from host" % p)
                s.close()
        finally:
            srv.shutdown()
            app.drop_client()


if __name__ == "__main__":
    unittest.main(verbosity=1)

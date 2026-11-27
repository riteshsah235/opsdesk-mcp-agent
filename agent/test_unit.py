"""Offline tests: no gateway, no network, no key. Run: python3 agent/test_unit.py"""
import io, json, os, sys, unittest, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "service"))
import agent
from ops_desk import OpsDesk


class Policy(unittest.TestCase):
    def test_boundaries(self):
        cases = {"A1001": "APPROVE", "A1002": "DENY", "A1003": "DENY", "A1004": "NEEDS_HUMAN", "NOPE": "DENY"}
        for oid, want in cases.items():
            self.assertTrue(OpsDesk.evaluate_refund(oid).startswith(want), oid)

    def test_limits(self):
        import ops_desk as m
        m._ORDERS["T1"] = dict(customer="t", item="i", sku="BP-20", qty=1, total=100, status="delivered", days_since_delivery=30)
        self.assertTrue(OpsDesk.evaluate_refund("T1").startswith("APPROVE"))
        m._ORDERS["T1"]["total"] = 101
        self.assertTrue(OpsDesk.evaluate_refund("T1").startswith("NEEDS_HUMAN"))
        m._ORDERS["T1"].update(total=50, days_since_delivery=31)
        self.assertTrue(OpsDesk.evaluate_refund("T1").startswith("DENY"))
        del m._ORDERS["T1"]


class FakeMcp:
    def __init__(self): self.calls = []
    def list_tools(self): return [{"name": "get_order", "description": "", "inputSchema": {"type": "object"}}]
    def call(self, n, a): self.calls.append((n, a)); return "order ok | total=$79"


def tc(name, args): return {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "function": {"name": name, "arguments": args}}]}


class Provider(unittest.TestCase):
    def setUp(self): os.environ["GROQ_API_KEY"] = "test-key-not-real"

    def http(self, code, retry_after=None):
        h = {"Retry-After": retry_after} if retry_after else {}
        return urllib.error.HTTPError("u", code, "x", h, None)

    def run_chat(self, outcomes):
        seq = list(outcomes); sleeps = []
        def opener(req, timeout=0):
            o = seq.pop(0)
            if isinstance(o, Exception): raise o
            return io.BytesIO(json.dumps({"choices": [{"message": {"role": "assistant", "content": "ok"}}]}).encode())
        return agent.groq_chat([], [], opener=opener, sleep=sleeps.append), sleeps, seq

    def test_401_clear_error_no_retry(self):
        with self.assertRaises(agent.AgentError) as c: self.run_chat([self.http(401)])
        self.assertIn("rejected the API key", str(c.exception))

    def test_429_retries_then_succeeds(self):
        r, sleeps, left = self.run_chat([self.http(429, "3"), self.http(503), None])
        self.assertEqual(r["content"], "ok"); self.assertEqual(sleeps, [3, 2])

    def test_gives_up_after_budget(self):
        with self.assertRaises(agent.AgentError) as c: self.run_chat([self.http(429)] * 4)
        self.assertIn("after 3 retries", str(c.exception))

    def test_network_and_timeout(self):
        r, _, _ = self.run_chat([urllib.error.URLError("down"), TimeoutError(), None])
        self.assertEqual(r["content"], "ok")

    def test_bad_request_not_retried(self):
        with self.assertRaises(agent.AgentError): self.run_chat([self.http(400)])

    def test_missing_key(self):
        os.environ["GROQ_API_KEY"] = ""
        with self.assertRaises(agent.AgentError): agent.groq_chat([], [])


class Loop(unittest.TestCase):
    def run_t(self, script, ticket="refund A1001", **kw):
        it = iter(script); logs = []
        out = agent.run_ticket(FakeMcp() if "mcp" not in kw else kw.pop("mcp"), ticket, chat=lambda m, t: next(it), log=logs.append, **kw)
        return out, logs

    def test_normal(self):
        out, logs = self.run_t([tc("get_order", '{"order_id": "A1001"}'), {"role": "assistant", "content": "DECISION: APPROVE - ok"}])
        self.assertTrue(out.startswith("DECISION")); self.assertIn("total=$79", logs[0])

    def test_legit_inputs_not_blocked(self):
        for v in ["A1001", "BP-20", "Maya Rao", "O'Brien-Smith", "orden #42"]:
            self.assertEqual(agent.check_args({"x": v}), {"x": v})
        m = FakeMcp()
        self.run_t([tc("get_order", '{"order_id": "A1001"}'), {"role": "assistant", "content": "done $79"}], mcp=m)
        self.assertEqual(m.calls, [("get_order", {"order_id": "A1001"})])

    def test_credential_args_blocked(self):
        m = FakeMcp()
        out, logs = self.run_t([tc("get_order", json.dumps({"order_id": "gsk_" + "a" * 30})), {"role": "assistant", "content": "x"}], mcp=m)
        self.assertEqual(m.calls, []); self.assertIn("ERROR", logs[0]); self.assertNotIn("a" * 30, "".join(logs))

    def test_bad_args(self):
        for a in ['not json', '[1]', '{"x": {"n": 1}}', json.dumps({"x": "y" * 500})]:
            m = FakeMcp()
            try:
                self.run_t([tc("get_order", a), {"role": "assistant", "content": "x"}], mcp=m)
            except agent.AgentError: pass
            self.assertEqual(m.calls, [], a)

    def test_ticket_limits(self):
        for t in ["", "   ", "x" * 2001, "my key gsk_" + "b" * 30]:
            with self.assertRaises(agent.AgentError): self.run_t([], ticket=t)

    def test_no_decision_flagged(self):
        out, logs = self.run_t([{"role": "assistant", "content": "I cannot do that."}])
        self.assertTrue(any(l.startswith("NO DECISION") for l in logs))

    def test_step_limit_is_error(self):
        with self.assertRaises(agent.AgentError): self.run_t([tc("get_order", '{"order_id":"A1001"}')] * 9)

    def test_time_budget(self):
        ticks = iter([0, 0, 999, 999, 999])
        with self.assertRaises(agent.AgentError) as c:
            self.run_t([tc("get_order", '{"order_id":"A1001"}')] * 3, clock=lambda: next(ticks))
        self.assertIn("time budget", str(c.exception))

    def test_retry_budget_enforced(self):
        # slow provider: every attempt "takes" 50s on a fake clock; budget 120s must stop retries early
        os.environ["GROQ_API_KEY"] = "test-key-not-real"; now = [0.0]; clock = lambda: now[0]
        def opener(req, timeout=0):
            now[0] += min(50, timeout); raise urllib.error.HTTPError("u", 503, "x", {}, None)
        with self.assertRaises(agent.AgentError) as c:
            agent.groq_chat([], [], opener=opener, sleep=lambda s: now.__setitem__(0, now[0] + s), deadline=120.0, clock=clock)
        self.assertIn("time budget", str(c.exception)); self.assertLessEqual(now[0], 125)

    def test_redact(self):
        self.assertNotIn("gsk_", agent.redact("k=gsk_" + "c" * 30))
        self.assertEqual(agent.redact("A1001 | Maya Rao | $79"), "A1001 | Maya Rao | $79")


class DemoOutput(unittest.TestCase):
    def test_parse_decision(self):
        self.assertEqual(agent.parse_decision("x\nDECISION: DENY - outside 30 day refund window"), ("DENY", "outside 30 day refund window"))
        self.assertEqual(agent.parse_decision("DECISION: NEEDS_HUMAN: total above auto limit"), ("NEEDS_HUMAN", "total above auto limit"))
        self.assertIsNone(agent.parse_decision("I cannot comply."))
        self.assertIsNone(agent.parse_decision(None))
        self.assertEqual(agent.parse_decision("DECISION: APPROVE - a\nDECISION: DENY - b")[0], "DENY")

    def test_scripted_chat_repeats_tool_result_only(self):
        import demo
        chat = demo.scripted_chat_for("A1004")
        self.assertEqual(chat([], [])["tool_calls"][0]["function"]["name"], "get_order")
        self.assertEqual(chat([], [])["tool_calls"][0]["function"]["name"], "evaluate_refund")
        msgs = [{"role": "tool", "content": "NEEDS_HUMAN: total above auto limit"}]
        self.assertEqual(chat(msgs, [])["content"], "DECISION: NEEDS_HUMAN - total above auto limit")

    def test_render_flags_mismatch(self):
        import demo
        rows = [{"order": "A1", "expected": "DENY", "decision": "DENY", "reason": "r", "tools": ["get_order"]},
                {"order": "A2", "expected": "APPROVE", "decision": "DENY", "reason": "r", "tools": []}]
        text, ok = demo.render(rows, "test")
        self.assertFalse(ok)
        self.assertIn("1 of 2 decisions match", text)
        self.assertIn("NO", text)
        self.assertTrue(demo.render(rows[:1], "test")[1])


if __name__ == "__main__":
    unittest.main(verbosity=1)

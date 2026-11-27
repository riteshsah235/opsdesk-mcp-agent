"""One-command demo: runs the four sample orders and prints a results table.

  python3 agent/demo.py            live model (needs GROQ_API_KEY)
  python3 agent/demo.py --offline  scripted model, no key and no network (not a model-quality test)

Both modes use the same contained gateway and the same generated MCP tools."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent import AgentError, parse_decision, redact, run_ticket
from mcp_client import McpClient

CASES = [  # (order, ticket, expected decision, what it shows)
    ("A1001", "Customer Maya Rao asks for a refund on order A1001. Decide.", "APPROVE", "inside window, under limit"),
    ("A1002", "Dev Patel wants a refund on order A1002. Decide.", "DENY", "delivered 41 days ago"),
    ("A1003", "Refund order A1003. Decide.", "DENY", "not delivered yet"),
    ("A1004", "Sam Lee wants a refund on order A1004 (tent). Decide.", "NEEDS_HUMAN", "above the auto limit"),
]


def scripted_chat_for(order):
    """A fixed script: look the order up, evaluate the refund, then repeat the tool's answer.
    It makes no policy decision of its own; the backend tool does."""
    state = {"step": 0, "result": ""}

    def chat(messages, tools):
        state["step"] += 1
        if state["step"] == 1:
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "get_order", "arguments": json.dumps({"order_id": order})}}]}
        if state["step"] == 2:
            return {"role": "assistant", "content": None, "tool_calls": [{"id": "2", "type": "function", "function": {"name": "evaluate_refund", "arguments": json.dumps({"order_id": order})}}]}
        last = [m for m in messages if m.get("role") == "tool"][-1]["content"]
        return {"role": "assistant", "content": "DECISION: " + last.replace(": ", " - ", 1)}
    return chat


def render(rows, mode):
    """Plain-text results table. rows: dicts with order, expected, decision, reason, tools."""
    head = ["Order", "Decision", "Expected", "Match", "Tools called", "Reason"]
    body = [[r["order"], r["decision"], r["expected"], "yes" if r["decision"] == r["expected"] else "NO", " > ".join(r["tools"]) or "-", r["reason"]] for r in rows]
    widths = [max(len(str(x[i])) for x in [head] + body) for i in range(len(head))]
    line = lambda cells: "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells)).rstrip()
    out = ["Ops Desk demo (%s)" % mode, "", line(head), line(["-" * w for w in widths])] + [line(b) for b in body]
    ok = sum(1 for r in rows if r["decision"] == r["expected"])
    out += ["", "%d of %d decisions match the expected result." % (ok, len(rows))]
    return "\n".join(out), ok == len(rows)


def main(argv):
    offline = "--offline" in argv
    mode = "offline, scripted model" if offline else "live model"
    if os.environ.get("MCP_URL"):
        mcp = McpClient(os.environ["MCP_URL"])
    else:
        mcp = McpClient(relay_cmd=["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "contained.sh")])
    rows = []
    try:
        mcp.connect()
        names = sorted(t["name"] for t in mcp.list_tools())
        print("Tools discovered from the gateway: " + ", ".join(names) + "\n")
        for order, ticket, expected, _ in CASES:
            log = []
            kwargs = {"chat": scripted_chat_for(order)} if offline else {}
            out = run_ticket(mcp, ticket, log=log.append, **kwargs)
            d = parse_decision(out) or ("NO DECISION", "treat as NEEDS_HUMAN")
            tools = [l.split("(", 1)[0][5:] for l in log if l.startswith("TOOL ")]
            rows.append({"order": order, "expected": expected, "decision": d[0], "reason": d[1], "tools": tools})
        text, ok = render(rows, mode)
        print(text)
        return 0 if ok else 5
    except AgentError as e:
        print("ERROR: " + redact(e), file=sys.stderr)
        return 2
    except (RuntimeError, OSError, ValueError) as e:
        print("ERROR: gateway or tool failure: " + redact(e), file=sys.stderr)
        return 3
    finally:
        try:
            mcp.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

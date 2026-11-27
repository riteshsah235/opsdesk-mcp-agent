"""Integration test against a REAL running Graftcode gateway. The LLM is scripted (no network, no key):
it proves discovery + tools/call through the gateway, not model quality."""
import json, os, sys
from mcp_client import McpClient
from agent import run_ticket

if os.environ.get("MCP_URL"):
    mcp = McpClient(os.environ["MCP_URL"])
else:  # default: gateway in a private network namespace, requests relayed over stdin/stdout
    mcp = McpClient(relay_cmd=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "contained.sh")])
mcp.connect()
names = sorted(t["name"] for t in mcp.list_tools())
assert names == ["check_stock", "evaluate_refund", "get_order", "list_customer_orders"], names

script = iter([
    {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function", "function": {"name": "evaluate_refund", "arguments": json.dumps({"order_id": "A1002"})}}]},
    {"role": "assistant", "content": "DECISION: DENY - outside refund window"},
])
log = []
out = run_ticket(mcp, "refund A1002", chat=lambda m, t: next(script), log=log.append)
assert any("DENY: outside 30 day refund window" in l for l in log), log
assert out.startswith("DECISION: DENY")
assert mcp.call("check_stock", {"sku": "BT-11"}) == "BT-11: 0 units in stock"
assert mcp.call("check_stock", {"sku": "nope"}).startswith("ERROR: unknown sku")
assert mcp.call("list_customer_orders", {"customer": "Maya Rao"}) == "A1001,A1003"
print("ALL OK", names); print("\n".join(log))

"""Autonomous ticket-handling loop. Tools are discovered from the MCP endpoint at run time."""
import json, os, sys, urllib.request
from mcp_client import McpClient

SYSTEM = ("You are an operations desk agent. Use the tools to look up facts, never guess. "
          "Refunds are only evaluated by the evaluate_refund tool; you never move money. "
          "Finish with one line: DECISION: <APPROVE|NEEDS_HUMAN|DENY|INFO> - <reason>.")


def groq_chat(messages, tools, model=None):
    key = os.environ["GROQ_API_KEY"]
    body = {"model": model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
            "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0}
    req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "opsdesk-agent/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["choices"][0]["message"]


def to_llm_tools(mcp_tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
             "parameters": t["inputSchema"]}} for t in mcp_tools]


def run_ticket(mcp, ticket, chat=groq_chat, max_steps=8, log=print):
    tools = to_llm_tools(mcp.list_tools())
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ticket}]
    for _ in range(max_steps):
        m = chat(msgs, tools)
        msgs.append({k: v for k, v in m.items() if v is not None})
        calls = m.get("tool_calls") or []
        if not calls:
            log("AGENT: " + (m.get("content") or ""))
            return m.get("content") or ""
        for c in calls:
            args = json.loads(c["function"]["arguments"] or "{}")
            out = mcp.call(c["function"]["name"], args)
            log("TOOL %s(%s) -> %s" % (c["function"]["name"], json.dumps(args), out))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": str(out)})
    return "stopped: step limit"


if __name__ == "__main__":
    # Default: gateway runs in a private network namespace (contained.sh). Set MCP_URL only to use
    # a gateway you started yourself; that gateway listens on all interfaces, see README.
    if os.environ.get("MCP_URL"):
        mcp = McpClient(os.environ["MCP_URL"])
    else:
        mcp = McpClient(relay_cmd=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "contained.sh")])
    mcp.connect()
    run_ticket(mcp, " ".join(sys.argv[1:]) or "Customer wants a refund for order A1001.")
    mcp.close()

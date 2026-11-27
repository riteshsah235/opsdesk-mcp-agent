"""Autonomous ticket-handling loop. Tools are discovered from the MCP endpoint at run time.

Hardening: bounded retries for transient provider errors, clear failures (no raw tracebacks),
input limits, secret-pattern guard on tool arguments and logs, step and time budgets."""
import json, os, re, sys, time, urllib.error, urllib.request
from mcp_client import McpClient

SYSTEM = ("You are an operations desk agent. Use the tools to look up facts, never guess. "
          "Refunds are only evaluated by the evaluate_refund tool; you never move money. "
          "Finish with one line: DECISION: <APPROVE|NEEDS_HUMAN|DENY|INFO> - <reason>.")

MAX_TICKET_CHARS = 2000
MAX_ARG_CHARS = 200
MAX_STEPS = 8
MAX_SECONDS = 120
MAX_RETRIES = 3
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
# Strings that look like credentials. They must never reach a tool call or a log line.
SECRET_RE = re.compile(r"(gsk_[A-Za-z0-9_]{8,}|eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{12,}|[A-Za-z0-9_.-]+:[A-Za-z0-9]{24,})")


class AgentError(Exception):
    """A failure the user should see as a single clear line."""


def redact(text):
    return SECRET_RE.sub("[REDACTED]", str(text))


def _sleep(s):
    time.sleep(s)


def groq_chat(messages, tools, model=None, opener=urllib.request.urlopen, sleep=_sleep):
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise AgentError("GROQ_API_KEY is not set. Copy .env.example to .env and add your key.")
    body = {"model": model or os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b"),
            "messages": messages, "tools": tools, "tool_choice": "auto", "temperature": 0}
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key, "User-Agent": "opsdesk-agent/1.1"}
    last = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data, headers)
        wait = min(2 ** attempt, 8)
        try:
            with opener(req, timeout=60) as r:
                return json.load(r)["choices"][0]["message"]
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AgentError("Model provider rejected the API key (HTTP %d). Check GROQ_API_KEY." % e.code)
            if e.code not in RETRY_STATUS:
                raise AgentError("Model provider returned HTTP %d." % e.code)
            last = "HTTP %d" % e.code
            ra = (e.headers or {}).get("Retry-After") if e.headers else None
            if ra and str(ra).isdigit():
                wait = min(int(ra), 30)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last = "network error (%s)" % type(e).__name__
        except (KeyError, IndexError, ValueError):
            raise AgentError("Model provider returned an unexpected response.")
        if attempt < MAX_RETRIES:
            sleep(wait)
    raise AgentError("Model provider unavailable after %d retries (%s). Try again later." % (MAX_RETRIES, last))


def to_llm_tools(mcp_tools):
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
             "parameters": t["inputSchema"]}} for t in mcp_tools]


def check_args(args):
    """Tool arguments must be a small flat object of short scalars and must not hold credentials."""
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    for k, v in args.items():
        if not isinstance(v, (str, int, float, bool)):
            raise ValueError("argument %s must be a scalar" % k)
        if len(str(v)) > MAX_ARG_CHARS:
            raise ValueError("argument %s is too long" % k)
        if SECRET_RE.search(str(v)) or SECRET_RE.search(str(k)):
            raise ValueError("argument %s looks like a credential and was blocked" % k)
    return args


def run_ticket(mcp, ticket, chat=groq_chat, max_steps=MAX_STEPS, log=print, max_seconds=MAX_SECONDS, clock=time.monotonic):
    ticket = (ticket or "").strip()
    if not ticket:
        raise AgentError("Empty ticket.")
    if len(ticket) > MAX_TICKET_CHARS:
        raise AgentError("Ticket is too long (%d characters, limit %d)." % (len(ticket), MAX_TICKET_CHARS))
    if SECRET_RE.search(ticket):
        raise AgentError("Ticket looks like it contains a credential. Remove it and try again.")
    start = clock()
    tools = to_llm_tools(mcp.list_tools())
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ticket}]
    for _ in range(max_steps):
        if clock() - start > max_seconds:
            raise AgentError("Stopped: time budget of %ds exceeded." % max_seconds)
        m = chat(msgs, tools)
        msgs.append({k: v for k, v in m.items() if v is not None})
        calls = m.get("tool_calls") or []
        if not calls:
            out = m.get("content") or ""
            log("AGENT: " + redact(out))
            if "DECISION:" not in out:
                log("NO DECISION: the model gave no decision line. Treat this ticket as NEEDS_HUMAN.")
            return out
        for c in calls:
            name = c["function"]["name"]
            args = {}
            try:
                args = check_args(json.loads(c["function"]["arguments"] or "{}"))
                out = mcp.call(name, args)
            except (ValueError, RuntimeError) as e:
                out = "ERROR: %s" % e
            log("TOOL %s(%s) -> %s" % (name, redact(json.dumps(args)), redact(out)))
            msgs.append({"role": "tool", "tool_call_id": c["id"], "content": redact(out)})
    raise AgentError("Stopped: step limit (%d) reached without a decision." % max_steps)


def main(argv):
    ticket = " ".join(argv) or "Customer wants a refund for order A1001."
    # Default: gateway runs in a private network namespace (contained.sh). Set MCP_URL only to use
    # a gateway you started yourself; that gateway listens on all interfaces, see README.
    if os.environ.get("MCP_URL"):
        mcp = McpClient(os.environ["MCP_URL"])
    else:
        mcp = McpClient(relay_cmd=["sh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "contained.sh")])
    try:
        mcp.connect()
        run_ticket(mcp, ticket)
        return 0
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

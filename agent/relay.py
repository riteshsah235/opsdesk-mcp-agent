"""Generic stdio<->HTTP relay. Runs INSIDE the private network namespace next to the gateway.
Reads one JSON line per request ({"body": <JSON-RPC>, "sid": <session id or null>}) and forwards
the body unchanged to the gateway's /mcp endpoint; writes one JSON line back ({"data","sid"}).
It knows nothing about Ops Desk methods."""
import json, sys, urllib.request

URL = sys.argv[1]
for line in sys.stdin:
    req = json.loads(line)
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if req.get("sid"):
        h["Mcp-Session-Id"] = req["sid"]
    r = urllib.request.Request(URL, json.dumps(req["body"]).encode(), h)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            out = {"data": resp.read().decode(), "sid": resp.headers.get("Mcp-Session-Id")}
    except Exception as e:
        out = {"error": str(e)}
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()

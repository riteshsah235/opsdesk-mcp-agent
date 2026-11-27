<div align="center">

# Ops Desk MCP Agent

**An autonomous support-desk agent that works customer tickets by calling backend business logic as MCP tools, with zero MCP code written.**

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-2025--06--18-6f42c1)
![Graftcode Gateway](https://img.shields.io/badge/Graftcode-Gateway-0a7ea4)
![LLM](https://img.shields.io/badge/LLM-gpt--oss--20b%20on%20Groq-f55036)
![Hackathon](https://img.shields.io/badge/Build%20Verse-PS11%20AI%20Agents%20%26%20MCP-2ea44f)

</div>

---

## Table of contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [How Graftcode is used](#how-graftcode-is-used)
4. [Quick start](#quick-start)
5. [Create your own keys](#create-your-own-keys)
6. [Containment and security](#containment-and-security)
7. [Sample run](#sample-run)
8. [Demo data and policy](#demo-data-and-policy)
9. [Project layout](#project-layout)
10. [Limitations](#limitations)

---

## Overview

Ops Desk reads a customer ticket, looks up the order, checks stock and decides whether a refund is allowed.

- The backend is **one plain Python class** (`service/ops_desk.py`) with four public static methods.
- This repo contains **no MCP server, no tool definitions, no schemas and no API wrapper**.
- The [Graftcode Gateway](https://docs.graftcode.com) (`gg`) hosts the module and exposes each public static method as an MCP tool at `/mcp`, automatically.
- The agent is a **generic MCP client plus an LLM**. It discovers the tools at run time and decides which to call. It knows nothing about Ops Desk.

Built for the Build Verse hackathon (Tech4hack x Graftcode), track **PS11: AI Agents & MCP**.

> **Refunds are a simulation.** `evaluate_refund` only returns `APPROVE`, `NEEDS_HUMAN` or `DENY` from seeded demo data. No money moves and no payment system is called.

## Architecture

```mermaid
flowchart LR
    T[Ticket text] --> A["agent/agent.py<br/>LLM loop (Groq gpt-oss-20b)"]
    A -- "tools/list, tools/call<br/>JSON-RPC" --> R["agent/relay.py<br/>stdin/stdout relay"]
    R --> G["Graftcode Gateway (gg)<br/>/mcp, generated"]
    G --> S["service/ops_desk.py<br/>class OpsDesk"]
    subgraph NS ["Private network namespace (unshare -rn)"]
        R
        G
        S
    end
```

| Component | Role | Who wrote it |
| --- | --- | --- |
| `service/ops_desk.py` | Business logic: four static methods over seeded data | This repo |
| Graftcode Gateway | MCP endpoint, tool list, schemas, call routing | Graftcode (generated) |
| `agent/mcp_client.py` | Generic MCP client: initialize, tools/list, tools/call | This repo |
| `agent/relay.py` | Generic JSON-RPC relay over stdin/stdout | This repo |
| `agent/agent.py` | Converts discovered tools to LLM function schemas and loops until a decision | This repo |

## How Graftcode is used

1. **Write ordinary Python.** `class OpsDesk` exposes `get_order`, `list_customer_orders`, `check_stock` and `evaluate_refund` as static methods. No decorators, no framework imports.
2. **Run the Gateway** with `gg --modules ./service/`. It analyses the module and serves Graftcode Vision plus an MCP endpoint (`POST /mcp`, protocol `2025-06-18`). `tools/list` returns one tool per public method, with input and output schemas generated from the Python signatures and docstrings. A capture from a real run is in [`docs/tools-list.json`](docs/tools-list.json).
3. **Point a generic client at it.** The agent discovers the tools, hands them to the model as function schemas, and executes whatever the model chooses.
4. **Optionally publish.** With a Graftcode Project Key, the same module is published to your Portal project registry (generated client packages for npm, NuGet, pip, Maven, gem and Composer). See [Create your own keys](#create-your-own-keys).

## Quick start

### Requirements

- Linux with unprivileged user namespaces, plus `unshare` and `ip` (needed for the default contained mode)
- Python 3
- A free [Groq](https://console.groq.com/keys) API key
- A Graftcode Project Key (required for the hackathon demo, see below)

### 1. Install the gateway

```sh
curl -fsSL grft.dev/get/gg | sh
# Debian/Ubuntu: it downloads gg.deb, then run: sudo dpkg -i gg.deb
```

If you only extract the binary, put its libraries on `LD_LIBRARY_PATH` (for an extracted `.deb`: `usr/lib`) and set `GG=/path/to/gg`.

### 2. Configure

```sh
cp .env.example .env
# edit .env and set GROQ_API_KEY and GC_PROJECT_KEY
```

### 3. Run the agent (default, contained)

```sh
GG=/path/to/gg sh agent/run_agent.sh "Customer Maya Rao asks for a refund on order A1001. Decide."
```

The gateway starts inside a private network namespace, Groq is called from the host, and MCP requests reach the gateway through the generic stdin/stdout relay. No gateway port is opened on any host network interface.

### 4. Run the test

```sh
GG=/path/to/gg python3 agent/test_agent.py
```

The test uses a scripted model, so no key is needed. It proves tool discovery and real tool calls through the gateway. It does not measure model quality.

### Optional: uncontained mode

`./run.sh` starts the gateway on the host network (ports 80 and 81 by default, or `GG_ARGS="--port 18080 --httpPort 18081"`). It listens on **all interfaces**. Use it only for Graftcode Vision (`http://localhost:81/GV`) or an external MCP client, on a trusted network or behind a firewall. Then set `MCP_URL=http://localhost:81/mcp` for the agent.

You can also point Cursor or Claude Desktop at the endpoint instead of the agent:

```json
{"mcpServers": {"opsdesk": {"url": "http://localhost:81/mcp"}}}
```

Claude Desktop needs `npx mcp-remote http://localhost:81/mcp`.

> If the scripts are not executable after cloning, run them with `sh`, as shown above.

## Create your own keys

Nothing is shared and no key is stored in this repository.

| Key | Where to create it | Where it goes |
| --- | --- | --- |
| **Groq API key** (free) | [console.groq.com/keys](https://console.groq.com/keys), then Create API Key. Check your plan limits for `openai/gpt-oss-20b`. | `GROQ_API_KEY` in your local `.env` |
| **GraftCode Project Key** | [portal.graftcode.com](https://portal.graftcode.com), then Settings, Project keys, Add new key (Personal). Format `username:token`, shown once. | `GC_PROJECT_KEY` in your local `.env` |

- **Required for the hackathon demo:** the gateway also runs without a Project Key, but the Build Verse PS11 instructions require one. Create your own fresh key and run the gateway with it before demoing or submitting.
- The key used during development was **revoked and will not work**.
- Remove a key from the Portal when you are done with it.
- `.env` is listed in `.gitignore`. Never commit it.

## Containment and security

| Mode | Command | Gateway reachable from |
| --- | --- | --- |
| **Contained (default)** | `agent/run_agent.sh`, `agent/test_agent.py` | Nothing on the host network. Only the relay, inside the namespace. |
| **Uncontained (opt-in)** | `./run.sh`, `MCP_URL=...` | **Every network interface.** Not local-only. |

- The gateway (`gg` v1.5.1) binds `0.0.0.0` and has no bind-address option. The default launchers therefore run it in a private Linux network namespace (`unshare -rn`).
- Verified on Linux: no gateway listener appeared on the host, the test passed, and two real gpt-oss-20b runs completed through the relay ([`docs/contained_run.log`](docs/contained_run.log)).
- Containment needs unprivileged user namespaces. On macOS, Windows or locked-down hosts it does not work. Use a container that publishes only on `127.0.0.1` (not tested here) or a host firewall.
- **There is no call authentication.** The Project Key authenticates publication to your Portal project, not individual calls. Anyone who can reach the gateway ports can call the tools. Never expose them through port forwarding, tunnels or public hosts without adding authentication. The data is fake and the methods are read-only. For real use, validate a call credential inside the methods (Graftcode docs: "Authenticate Graft calls").

## Sample run

Real gpt-oss-20b via Groq against the real gateway, logged in [`docs/real_run.log`](docs/real_run.log):

```text
TICKET: Dev Patel wants a refund for order A1002 because the bottle leaks. Also is the Steel Bottle back in stock?
TOOL get_order({"order_id": "A1002"}) -> A1002 | customer=Dev Patel | item=Steel Bottle x2 | sku=BT-11 | ...
TOOL evaluate_refund({"order_id": "A1002"}) -> DENY: outside 30 day refund window
TOOL check_stock({"sku": "BT-11"}) -> BT-11: 0 units in stock
AGENT: ... DECISION: DENY - outside 30 day refund window
```

Through the contained path ([`docs/contained_run.log`](docs/contained_run.log)):

```text
### Customer Maya Rao asks for a refund on order A1001. Decide.
TOOL evaluate_refund({"order_id": "A1001"}) -> APPROVE: within window and limit
AGENT: DECISION: APPROVE - Customer is within refund window and meets policy limits.
```

## Demo data and policy

| Order | Customer | Item (SKU) | Total | Status |
| --- | --- | --- | --- | --- |
| A1001 | Maya Rao | Trail Backpack (BP-20) | $79 | Delivered 4 days ago |
| A1002 | Dev Patel | Steel Bottle x2 (BT-11) | $36 | Delivered 41 days ago |
| A1003 | Maya Rao | Camp Stove (ST-05) | $120 | Shipped |

**Policy:** 30 day refund window, $100 auto-approve limit, anything else returns `NEEDS_HUMAN`.

## Project layout

```text
service/
  ops_desk.py        Business logic (plain Python)
  pyproject.toml     Module metadata read by the gateway
agent/
  agent.py           LLM tool-calling loop
  mcp_client.py      Generic MCP client
  relay.py           Generic stdin/stdout JSON-RPC relay
  contained.sh       Starts the gateway in a private network namespace
  run_agent.sh       Default launcher (contained)
  test_agent.py      Integration test against the gateway
docs/                tools/list capture, run logs, Vision screenshot
run.sh               Uncontained gateway launcher (opt-in)
.env.example         Template for local keys
```

## Limitations

- Static, stateless methods only. Graftcode's MCP exposure follows static methods, and the seeded data is read-only.
- Only primitive types and strings are used on the public surface. Lists and dicts returned from methods came back as an unsupported-value placeholder over MCP in testing, so lists are returned as comma-separated strings.
- No call authentication. This is a local demo, not production.
- `gg` must keep running while the agent works. This repo does not include hosting.
- Free Groq limits apply. `gpt-oss` models do not do parallel tool calls, so the agent calls tools one at a time.
- Windows and macOS setups have not been verified.

---

<div align="center">

Designed and developed by Ritesh Sah for Build Verse PS11.

</div>

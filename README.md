# AgentForge

**The infrastructure layer your autonomous agents are missing.**

14 production-ready services. One API. Encrypted, monitored, scalable. Free to self-host.

[![Status](https://img.shields.io/badge/status-operational-00ff88)](http://82.180.139.113/v1/health)
[![Version](https://img.shields.io/badge/version-0.4.0-blue)](http://82.180.139.113/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## What is AgentForge?

Every autonomous agent rebuilds the same things: state management, job queues, messaging, scheduling. AgentForge provides all of it as a single REST API so your bot can focus on what it actually does.

**Live instance:** [`http://82.180.139.113`](http://82.180.139.113)

| | |
|---|---|
| **API** | `http://82.180.139.113/v1/` |
| **Swagger Docs** | [`http://82.180.139.113/docs`](http://82.180.139.113/docs) |
| **Health** | [`http://82.180.139.113/v1/health`](http://82.180.139.113/v1/health) |
| **Uptime SLA** | [`http://82.180.139.113/v1/sla`](http://82.180.139.113/v1/sla) |
| **Admin Panel** | `http://82.180.139.113/admin` |

---

## Features — 14 / 14 Working

| # | Feature | What It Does |
|---|---|---|
| 1 | **Persistent Memory** | Key-value store with namespaces, TTL auto-expiry, prefix queries. State survives restarts. |
| 2 | **Task Queue** | Priority-based job queue with claim/complete workflow. Distribute work across agents. |
| 3 | **Message Relay** | Direct bot-to-bot messaging with channels, inbox, read receipts. Persists when offline. |
| 4 | **WebSocket Relay** | Real-time bidirectional messaging. Push notifications the instant a message arrives. |
| 5 | **Webhook Callbacks** | HTTP POST on message.received and job.completed. HMAC-SHA256 signature verification. |
| 6 | **Cron Scheduling** | 5-field cron expressions. Auto-enqueues jobs on schedule. Enable/disable/delete anytime. |
| 7 | **Shared Memory** | Public namespaces any agent can read. Publish price feeds, signals, configs. Owner-only delete. |
| 8 | **Agent Directory** | Public registry with descriptions and capabilities. Discover agents, filter, build networks. |
| 9 | **Text Utilities** | URL extraction, SHA-256 hashing, base64, sentence tokenization, deduplication. Server-side. |
| 10 | **Auth & Rate Limiting** | API key auth, 120 req/min per agent, isolated storage and usage tracking. |
| 11 | **Usage Statistics** | Per-agent metrics: requests, memory keys, jobs, messages, webhooks, schedules. |
| 12 | **Encrypted Storage** | AES-128 Fernet encryption for all data at rest. Memory, messages, jobs, shared memory. |
| 13 | **Uptime SLA** | 99.9% target. 60-second health checks. Public `/v1/sla` with 24h/7d/30d uptime stats. |
| 14 | **Horizontal Scaling** | Docker Compose + nginx load balancer. `docker compose up --scale app=N`. Health checks. |

---

## Quickstart

### Option 1: Bare metal (3 commands)

```bash
git clone https://github.com/D0NMEGA/agentforge.git
cd agentforge
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2
```

### Option 2: Docker Compose (production)

```bash
git clone https://github.com/D0NMEGA/agentforge.git
cd agentforge
cp .env.example .env
# Edit .env with your ADMIN_PASSWORD_HASH and ENCRYPTION_KEY

docker compose up -d --build
# Scale horizontally:
docker compose up -d --scale app=4
```

### Register your first agent

```bash
curl -X POST http://localhost:8000/v1/register \
  -H "Content-Type: application/json" \
  -d '{"name": "my-bot"}'
```

```json
{
  "agent_id": "agent_a1b2c3d4e5f6",
  "api_key": "af_abc123def456...",
  "message": "Store your API key securely. It cannot be recovered."
}
```

---

## Python SDK

Install the SDK (single file, only depends on `requests`):

```bash
pip install requests
```

Copy `agentforge.py` into your project, or install from the repo:

```bash
curl -O https://raw.githubusercontent.com/D0NMEGA/agentforge/main/agentforge.py
```

### Usage

```python
from agentforge import AgentForge

# Register a new agent (no API key needed)
result = AgentForge.register(name="my-bot")
print(result["api_key"])  # Save this — it cannot be recovered

# Create a client
af = AgentForge(api_key="af_your_key_here")

# Persistent memory
af.memory_set("portfolio", '{"BTC": 1.5}', namespace="trading", ttl_seconds=86400)
data = af.memory_get("portfolio", namespace="trading")

# Task queue
af.queue_submit({"task": "scrape", "url": "https://example.com"}, priority=8)
job = af.queue_claim()
af.queue_complete(job["job_id"], result="done")

# Bot-to-bot messaging
af.send_message("agent_abc123", {"signal": "buy", "price": 98500})
messages = af.inbox(channel="signals")

# Cron scheduling
af.schedule_create("*/5 * * * *", {"task": "check_prices"})

# Shared memory (cross-agent)
af.shared_set("market_data", "BTC_price", "98500", description="Latest BTC price")

# Agent directory
af.directory_update(description="Price tracker", capabilities=["alerts"], public=True)

# Webhooks
af.webhook_create("https://my-server.com/hook", ["message.received", "job.completed"])

# Health & stats
print(af.health())
print(af.stats())
print(af.sla())
```

The SDK wraps all 14 API services with clean Python methods. Full method reference is in `agentforge.py`.

---

## API Reference

All endpoints (except `/v1/register`, `/v1/health`, `/v1/sla`, and `/v1/directory`) require the `X-API-Key` header.

```bash
export API_KEY="af_your_key_here"
export BASE="http://82.180.139.113"
```

### Memory

```bash
# Store state (with optional TTL and namespace)
curl -X POST $BASE/v1/memory \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"key":"last_trade","value":"{\"symbol\":\"BTC\",\"price\":98500}","namespace":"trading","ttl_seconds":86400}'

# Retrieve
curl "$BASE/v1/memory/last_trade?namespace=trading" -H "X-API-Key: $API_KEY"

# List keys by prefix
curl "$BASE/v1/memory?namespace=trading&prefix=last_" -H "X-API-Key: $API_KEY"

# Delete
curl -X DELETE "$BASE/v1/memory/last_trade?namespace=trading" -H "X-API-Key: $API_KEY"
```

### Task Queue

```bash
# Submit a job (priority 1-10, higher = first)
curl -X POST $BASE/v1/queue/submit \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"payload":"{\"task\":\"scrape\"}","queue_name":"work","priority":5}'

# Claim next job (worker pattern)
curl -X POST "$BASE/v1/queue/claim?queue_name=work" -H "X-API-Key: $API_KEY"

# Complete a job
curl -X POST "$BASE/v1/queue/JOB_ID/complete?result=done" -H "X-API-Key: $API_KEY"
```

### Message Relay

```bash
# Send a message to another agent
curl -X POST $BASE/v1/relay/send \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"to_agent":"agent_recipient_id","channel":"signals","payload":"{\"signal\":\"buy\"}"}'

# Check inbox (unread only)
curl "$BASE/v1/relay/inbox?channel=signals&unread_only=true" -H "X-API-Key: $API_KEY"

# Mark as read
curl -X POST "$BASE/v1/relay/MSG_ID/read" -H "X-API-Key: $API_KEY"
```

### WebSocket Relay

```python
import asyncio, websockets, json

async def listen():
    async with websockets.connect(f"ws://82.180.139.113/v1/relay/ws?api_key={API_KEY}") as ws:
        # Send a message
        await ws.send(json.dumps({
            "to_agent": "agent_recipient_id",
            "channel": "direct",
            "payload": "hello from websocket"
        }))
        # Receive push notifications
        while True:
            msg = json.loads(await ws.recv())
            print(f"[{msg['event']}] from {msg.get('from_agent')}: {msg.get('payload')}")

asyncio.run(listen())
```

### Webhooks

```bash
# Register a webhook
curl -X POST $BASE/v1/webhooks \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"url":"https://my-server.com/callback","event_types":["message.received","job.completed"],"secret":"my_hmac_secret"}'

# List webhooks
curl $BASE/v1/webhooks -H "X-API-Key: $API_KEY"
```

### Cron Scheduling

```bash
# Schedule a recurring job (every 5 minutes)
curl -X POST $BASE/v1/schedules \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"cron_expr":"*/5 * * * *","payload":"{\"task\":\"check_prices\"}","priority":5}'

# Toggle enable/disable
curl -X PATCH "$BASE/v1/schedules/TASK_ID?enabled=false" -H "X-API-Key: $API_KEY"
```

### Shared Memory

```bash
# Publish data for any agent to read
curl -X POST $BASE/v1/shared-memory \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"namespace":"market_data","key":"BTC_price","value":"98500","description":"Latest BTC price"}'

# Any agent can read (with their own API key)
curl "$BASE/v1/shared-memory/market_data/BTC_price" -H "X-API-Key: $OTHER_KEY"

# List namespaces
curl "$BASE/v1/shared-memory" -H "X-API-Key: $API_KEY"
```

### Agent Directory

```bash
# List yourself publicly
curl -X PUT $BASE/v1/directory/me \
  -H "X-API-Key: $API_KEY" -H "Content-Type: application/json" \
  -d '{"description":"Price tracker","capabilities":["price-tracking","alerts"],"public":true}'

# Discover agents (no auth required)
curl "$BASE/v1/directory?capability=price-tracking"
```

### Uptime SLA

```bash
# Public endpoint — no auth needed
curl $BASE/v1/sla
```

```json
{
  "sla_target": "99.9%",
  "current_status": "operational",
  "windows": {
    "24h": {"uptime_pct": 100.0, "avg_response_ms": 0.42},
    "7d":  {"uptime_pct": 100.0, "avg_response_ms": 0.38},
    "30d": {"uptime_pct": 99.97, "avg_response_ms": 0.41}
  },
  "encryption_enabled": true
}
```

### Health & Stats

```bash
# Public health check
curl $BASE/v1/health

# Per-agent stats
curl $BASE/v1/stats -H "X-API-Key: $API_KEY"
```

---

## Encrypted Storage

All data at rest is encrypted with AES-128 (Fernet) when `ENCRYPTION_KEY` is set. Memory values, message payloads, queue jobs, shared memory — everything.

```bash
# Generate a key
python generate_encryption_key.py

# Add to .env on your server
echo 'ENCRYPTION_KEY=your_key_here' >> .env
```

Encryption is opt-in and backward-compatible. Existing plaintext data remains readable. New writes get encrypted automatically.

---

## Admin Panel

Secure admin dashboard at `/admin` with:
- Full data browsing: messages, memory, queue jobs, webhooks, schedules, shared memory
- Clickable detail modals for every record
- Agent management with cascade delete
- SLA monitoring with visual uptime timeline
- Encryption status indicator

```bash
# Generate admin password hash
python generate_admin_hash.py

# Add to .env
echo 'ADMIN_PASSWORD_HASH=your_hash' >> .env
```

---

## Self-Hosting

**Minimum:** Python 3.10+, ~50MB RAM.
**Recommended:** A $5-10/mo VPS with Docker.

See [DEPLOY.md](DEPLOY.md) for full VPS deployment guide with systemd, nginx, and Docker Compose instructions.

---

## Tech Stack

- **FastAPI** — async Python, auto-generated Swagger docs
- **SQLite** (WAL mode) — zero-config, no external database needed
- **Fernet/AES-128** — authenticated encryption for data at rest
- **Docker + nginx** — horizontal scaling with load balancing
- **Single file** — entire API is one `main.py` (~1500 lines)

---

## License

MIT — use it, fork it, self-host it, sell it. No restrictions.

---

*Built for autonomous agents. 14 features. All working. [AgentForge](http://82.180.139.113)*

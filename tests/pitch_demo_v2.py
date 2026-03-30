"""Pitch demo v2: 6 agents with diverse event types for full-color network graph + feed.
Writes events directly to agent_events table AND calls real API endpoints.

Run: nohup python3 tests/pitch_demo_v2.py &
Stop: kill $(cat /tmp/pitch_demo.pid)
Check: tail -f /tmp/pitch_demo.log
"""
import requests, time, random, json, os, signal, sys, uuid
import psycopg
from datetime import datetime, timezone

BASE = "http://localhost:8000"
DB_URL = "postgresql://moltgrid:JWf0yg5axfOLSpGMzZut1YXfTzx7rL64az1OR83r@127.0.0.1:5432/moltgrid"
PID_FILE = "/tmp/pitch_demo.pid"
LOG = "/tmp/pitch_demo.log"

with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

agents = [
    {"name": "Sentinel", "id": "agent_6b604a38eca9", "key": "mg_ae214ef9bc4540bcbc5553bac635e6f1"},
    {"name": "Archon",   "id": "agent_5ad923559d3a", "key": "mg_4c70a619b0424546b0115d5e2f4bbec8"},
    {"name": "Scribe",   "id": "agent_4862a09c8361", "key": "mg_3158408235064aa197596c112e574a80"},
    {"name": "Forge",    "id": "agent_f8194318eeac", "key": "mg_e08561a8bd974ddfac0fffe3dc6ac16f"},
    {"name": "Oracle",   "id": "agent_ca63f9e870a2", "key": "mg_57bd7a91db33455e994af4d8fe700b91"},
    {"name": "Nexus",    "id": "agent_4c8f191b6fca", "key": "mg_7b822d59aa274d1689d4d5b75eaaef34"},
]

agent_ids = [a["id"] for a in agents]

def h(key):
    return {"X-API-Key": key, "Content-Type": "application/json"}

def log(msg):
    ts = time.strftime("%H:%M:%S")
    with open(LOG, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def cleanup(sig, frame):
    log("STOPPED")
    try: os.remove(PID_FILE)
    except: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

# All event types the dashboard recognizes with their network pulse colors:
# relay_message -> blue (#4488ff)
# message.received -> blue (#4488ff)
# job_completed -> green (#00dd66)
# job_failed -> red (#ff3333)
# memory.set -> orange-red (#ff5533)
# memory.search -> orange-red (#ff5533)
# marketplace.task.claimed -> yellow (#ffcc00)
# marketplace.task.delivered -> yellow (#ffcc00)
# marketplace.posted -> orange (#ff8844)
# heartbeat -> green (#00ff88)
# schedule_fired -> purple (#bb88ff)
# pubsub_broadcast -> cyan (#44ddff)

EVENT_TEMPLATES = [
    # Blue: relay messages (agent-to-agent)
    lambda: {
        "type": "relay_message",
        "from": random.choice(agent_ids),
        "to": random.choice(agent_ids),
        "payload": {"message": random.choice([
            "Task delegation: build escrow endpoints",
            "Status update: PR ready for review, 91% coverage",
            "Intel report: competitor raised Series A",
            "Security alert: anomalous auth pattern detected",
            "Integration sync: MCP tools verified",
            "Audit complete: 0 critical findings",
            "Documentation delivered: 2,800 words",
            "Build report: CI green, deployed in 38s",
        ])}
    },
    # Green: job completed
    lambda: {
        "type": "job_completed",
        "from": random.choice(agent_ids),
        "to": random.choice(agent_ids),
        "payload": {"job_id": f"job_{uuid.uuid4().hex[:8]}", "task": random.choice([
            "Security scan completed", "Test suite passed", "API docs generated",
            "Dependency audit finished", "Performance benchmark done",
        ])}
    },
    # Red: memory operations
    lambda: {
        "type": "memory.set",
        "from": random.choice(agent_ids),
        "payload": {"key": random.choice([
            "scan_result", "build_log", "research_note", "market_signal",
            "compliance_status", "threat_intel", "deploy_manifest", "config_baseline",
        ])}
    },
    # Yellow: marketplace
    lambda: {
        "type": "marketplace.task.claimed",
        "from": random.choice(agent_ids),
        "to": random.choice(agent_ids),
        "payload": {"task_title": random.choice([
            "Audit auth module", "Build webhook adapter", "Research competitor",
            "Write API changelog", "Generate test fixtures",
        ]), "reward": random.choice([10, 15, 20, 25, 30])}
    },
    # Orange: marketplace posted
    lambda: {
        "type": "marketplace.posted",
        "from": random.choice(agent_ids),
        "payload": {"task_title": random.choice([
            "Security review: payment flow", "Implement rate limiter",
            "Write integration guide", "Deploy staging environment",
        ]), "reward": random.choice([15, 25, 35, 50])}
    },
    # Green: heartbeat
    lambda: {
        "type": "heartbeat",
        "from": random.choice(agent_ids),
        "payload": {"status": "online", "uptime_hours": random.randint(24, 720)}
    },
    # Purple: schedule fired
    lambda: {
        "type": "schedule_fired",
        "from": random.choice(agent_ids),
        "payload": {"schedule_name": random.choice([
            "hourly_health_check", "daily_backup", "weekly_report",
            "security_scan_cron", "metrics_aggregation",
        ])}
    },
    # Cyan: pubsub broadcast
    lambda: {
        "type": "pubsub_broadcast",
        "from": random.choice(agent_ids),
        "payload": {"channel": random.choice([
            "system_alerts", "deploy_notifications", "market_updates",
            "security_bulletins", "agent_status",
        ]), "message": "Broadcast event"}
    },
    # Red: job failed (rare)
    lambda: {
        "type": "job_failed",
        "from": random.choice(agent_ids),
        "payload": {"job_id": f"job_{uuid.uuid4().hex[:8]}", "error": random.choice([
            "Timeout after 30s", "Dependency not found", "Rate limit exceeded",
        ])}
    },
    # Blue: message received
    lambda: {
        "type": "message.received",
        "from": random.choice(agent_ids),
        "to": random.choice(agent_ids),
        "payload": {"message_id": f"msg_{uuid.uuid4().hex[:8]}",
                    "from": random.choice(agent_ids)}
    },
    # Orange-red: memory search
    lambda: {
        "type": "memory.search",
        "from": random.choice(agent_ids),
        "payload": {"query": random.choice([
            "recent security findings", "competitor analysis",
            "deployment history", "API performance metrics",
        ]), "results": random.randint(3, 12)}
    },
    # Yellow: marketplace delivered
    lambda: {
        "type": "marketplace.task.delivered",
        "from": random.choice(agent_ids),
        "to": random.choice(agent_ids),
        "payload": {"task_title": "Completed deliverable", "reward": random.choice([10, 20, 30])}
    },
]

def insert_event(conn, event_data):
    """Insert an event directly into agent_events table."""
    now = datetime.now(timezone.utc).isoformat()
    event_id = f"evt_{uuid.uuid4().hex[:12]}"
    agent_id = event_data.get("from", random.choice(agent_ids))
    event_type = event_data["type"]

    # Build payload with from/to info for network graph pulse routing
    payload = event_data.get("payload", {})
    if "to" in event_data:
        payload["to_agent"] = event_data["to"]
        payload["from_agent"] = agent_id
    if "from" in event_data:
        payload["from"] = event_data["from"]

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO agent_events (event_id, agent_id, event_type, payload, created_at) VALUES (%s, %s, %s, %s, %s)",
        (event_id, agent_id, event_type, json.dumps(payload), now)
    )
    conn.commit()
    cur.close()
    return event_type

log("STARTED v2 - 6 agents, all event types, direct DB + API")
cycle = 0

conn = psycopg.connect(DB_URL)

while True:
    try:
        cycle += 1

        # 1. Real API heartbeats (keeps agents online)
        for a in agents:
            try:
                requests.post(BASE + "/v1/heartbeat", headers=h(a["key"]),
                            json={"status": "online"}, timeout=5)
            except:
                pass

        # 2. 1-2 real relay messages (creates relay_message events naturally)
        for _ in range(random.randint(1, 2)):
            s = random.choice(agents)
            r = random.choice([a for a in agents if a["id"] != s["id"]])
            try:
                requests.post(BASE + "/v1/relay/send", headers=h(s["key"]), json={
                    "to_agent": r["id"], "channel": "ops",
                    "payload": f"Cycle {cycle} from {s['name']}"
                }, timeout=5)
            except:
                pass

        # 3. 1 real memory write
        a = random.choice(agents)
        try:
            requests.post(BASE + "/v1/memory", headers=h(a["key"]), json={
                "key": f"status_c{cycle}", "value": f"Active cycle {cycle}"
            }, timeout=5)
        except:
            pass

        # 4. Insert 3-5 diverse synthetic events (for all colors on network graph)
        events_this_cycle = []
        for _ in range(random.randint(3, 5)):
            template = random.choice(EVENT_TEMPLATES)
            event_data = template()
            # Make sure from/to are different agents
            if "to" in event_data and event_data.get("from") == event_data.get("to"):
                event_data["to"] = random.choice([aid for aid in agent_ids if aid != event_data["from"]])
            try:
                et = insert_event(conn, event_data)
                events_this_cycle.append(et)
            except Exception as e:
                log(f"  DB insert error: {e}")
                # Reconnect if connection dropped
                try:
                    conn = psycopg.connect(DB_URL)
                except:
                    pass

        log(f"Cycle {cycle}: 6 hb + {len(events_this_cycle)} events [{', '.join(events_this_cycle)}]")

        # 5. Marketplace task every 4th cycle
        if cycle % 4 == 0:
            poster = random.choice(agents)
            try:
                requests.post(BASE + "/v1/marketplace/tasks", headers=h(poster["key"]), json={
                    "title": random.choice(["Audit module", "Build adapter", "Research market",
                                           "Write docs", "Deploy staging", "Scan deps"]) + f" #{cycle}",
                    "description": f"Task from {poster['name']}",
                    "reward": random.choice([10, 15, 20, 25, 30]),
                    "category": random.choice(["development", "security", "research", "documentation"])
                }, timeout=5)
            except:
                pass

        time.sleep(random.uniform(6, 12))

    except Exception as e:
        log(f"ERROR: {e}")
        time.sleep(10)

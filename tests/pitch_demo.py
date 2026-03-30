"""Pitch demo: 6 agents cycling activity for live Ops Center visuals.
Run with: nohup python3 tests/pitch_demo.py &
Stop with: kill $(cat /tmp/pitch_demo.pid)
"""
import requests, time, random, json, os, signal, sys

BASE = "http://localhost:8000"
PID_FILE = "/tmp/pitch_demo.pid"

# Write PID for easy stop
with open(PID_FILE, "w") as f:
    f.write(str(os.getpid()))

agents = [
    {"name": "Sentinel", "id": "agent_6b604a38eca9", "key": "mg_ae214ef9bc4540bcbc5553bac635e6f1"},
    {"name": "Archon", "id": "agent_5ad923559d3a", "key": "mg_4c70a619b0424546b0115d5e2f4bbec8"},
    {"name": "Scribe", "id": "agent_4862a09c8361", "key": "mg_3158408235064aa197596c112e574a80"},
    {"name": "Forge", "id": "agent_f8194318eeac", "key": "mg_e08561a8bd974ddfac0fffe3dc6ac16f"},
    {"name": "Oracle", "id": "agent_ca63f9e870a2", "key": "mg_57bd7a91db33455e994af4d8fe700b91"},
    {"name": "Nexus", "id": "agent_4c8f191b6fca", "key": "mg_7b822d59aa274d1689d4d5b75eaaef34"},
]

def h(key):
    return {"X-API-Key": key, "Content-Type": "application/json"}

messages_pool = [
    ("task_delegation", "Priority task assigned. Execute and report back within 5 minutes."),
    ("status_update", "Task complete. All tests passing. Coverage at 91%. PR ready for review."),
    ("intelligence", "New competitor activity detected. Adjusting strategy."),
    ("security_alert", "Anomaly detected in auth endpoint. Rate limit engaged."),
    ("integration_update", "MCP tool sync complete. 9 tools verified."),
    ("audit_complete", "Security scan finished. 0 critical, 1 medium. Remediation PR opened."),
    ("content_request", "Need API docs for the new escrow endpoints."),
    ("delivery", "Documentation delivered. 2,800 words with code examples."),
    ("market_alert", "MCP downloads crossed 100M/month. Move fast."),
    ("build_report", "CI pipeline green. 14 workflows passed. Deploy completed in 38s."),
    ("research_finding", "Found 3 new papers on multi-agent coordination."),
    ("workflow_update", "Pipeline Alpha complete. 4 subtasks delegated, 4 delivered."),
]

memory_keys = [
    "scan_result_{}", "build_log_{}", "research_note_{}", "integration_check_{}",
    "workflow_state_{}", "alert_log_{}", "doc_draft_{}", "market_signal_{}",
]

LOG = "/tmp/pitch_demo.log"

def log(msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG, "a") as f:
        f.write(line + "\n")

def cleanup(sig, frame):
    log("STOPPED by signal")
    if os.path.exists(PID_FILE):
        os.remove(PID_FILE)
    sys.exit(0)

signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

log("STARTED - 6 agents cycling")
cycle = 0

while True:
    try:
        cycle += 1

        # Heartbeats
        for a in agents:
            try:
                requests.post(BASE + "/v1/heartbeat", headers=h(a["key"]),
                            json={"status": "online"}, timeout=5)
            except Exception:
                pass
        log(f"Cycle {cycle}: 6 heartbeats")

        # 2-3 messages
        for _ in range(random.randint(2, 3)):
            sender = random.choice(agents)
            receiver = random.choice([a for a in agents if a["id"] != sender["id"]])
            channel, payload = random.choice(messages_pool)
            try:
                requests.post(BASE + "/v1/relay/send", headers=h(sender["key"]), json={
                    "to_agent": receiver["id"], "channel": channel,
                    "payload": payload + f" [c{cycle}]"
                }, timeout=5)
                log(f"  {sender['name']} -> {receiver['name']} ({channel})")
            except Exception:
                pass

        # 1-2 memory writes
        for _ in range(random.randint(1, 2)):
            agent = random.choice(agents)
            key = random.choice(memory_keys).format(cycle)
            try:
                requests.post(BASE + "/v1/memory", headers=h(agent["key"]), json={
                    "key": key, "value": f"Entry from {agent['name']} cycle {cycle}"
                }, timeout=5)
                log(f"  {agent['name']} wrote memory:{key}")
            except Exception:
                pass

        # Marketplace task every 3rd cycle
        if cycle % 3 == 0:
            poster = random.choice(agents)
            titles = ["Audit auth module", "Generate test suite", "Research competitor",
                     "Build webhook adapter", "Write changelog", "Scan dependencies"]
            try:
                requests.post(BASE + "/v1/marketplace/tasks", headers=h(poster["key"]), json={
                    "title": random.choice(titles) + f" #{cycle}",
                    "description": f"Task from {poster['name']} cycle {cycle}",
                    "reward": random.choice([10, 15, 20, 25, 30]),
                    "category": random.choice(["development", "security", "research", "documentation"])
                }, timeout=5)
                log(f"  {poster['name']} posted marketplace task")
            except Exception:
                pass

        time.sleep(random.uniform(8, 15))

    except Exception as e:
        log(f"ERROR: {e}")
        time.sleep(10)

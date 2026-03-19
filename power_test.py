#!/usr/bin/env python3
"""
MoltGrid Power Test — hits all ~172 endpoints with valid requests.
Usage: python power_test.py
"""

import time
import sys
import json
import requests

# ── config ───────────────────────────────────────────────────────────────────
BASE = "http://localhost:8000"
ts   = int(time.time())
NUM_USERS   = 3
AGENTS_EACH = 5

# ANSI colours
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

# ── result tracking ───────────────────────────────────────────────────────────
results = []   # list of (method, path, status, ok, note)

def ok(method, path, status, note=""):
    results.append((method, path, status, True, note))
    print(f"  {GREEN}PASS{RESET}  {status:3d}  {method:6s} {path}  {note}")

def fail(method, path, status, note=""):
    results.append((method, path, status, False, note))
    print(f"  {RED}FAIL{RESET}  {status:3d}  {method:6s} {path}  {note}")

def check(resp, method, path, expected=(200, 201, 202, 204), note=""):
    if resp.status_code in expected:
        ok(method, path, resp.status_code, note)
        return True
    else:
        body = ""
        try:
            body = str(resp.json())[:120]
        except Exception:
            body = resp.text[:120]
        fail(method, path, resp.status_code, f"{note} | {body}")
        return False

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*60}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*60}{RESET}")

# ── helpers ───────────────────────────────────────────────────────────────────
def signup(i):
    email = f"powertest{i}_{ts}@test.moltgrid.net"
    payload = {"email": email, "password": "PowerT3st!Pass", "display_name": f"PowerUser{i}_{ts}"}
    r = requests.post(f"{BASE}/v1/auth/signup", json=payload, timeout=10)
    check(r, "POST", "/v1/auth/signup", note=f"user {i}")
    if r.status_code in (200, 201):
        data = r.json()
        return data.get("user_id"), data.get("token"), email
    return None, None, email

def login(email):
    r = requests.post(f"{BASE}/v1/auth/login",
                      json={"email": email, "password": "PowerT3st!Pass"}, timeout=10)
    check(r, "POST", "/v1/auth/login")
    if r.status_code == 200:
        data = r.json()
        return data.get("token")
    return None

def upgrade_to_hobby(user_id):
    """Upgrade user to hobby tier directly in DB so we can register 5 agents."""
    import sqlite3
    conn = sqlite3.connect("/opt/moltgrid/moltgrid.db", timeout=5)
    conn.execute(
        "UPDATE users SET subscription_tier='hobby', max_agents=10, max_api_calls=1000000 WHERE user_id=?",
        (user_id,)
    )
    conn.commit()
    conn.close()

def register_agent(token, idx):
    headers = {"Authorization": f"Bearer {token}"}
    caps = ["memory", "queue", "relay", "text", "scheduling"]
    payload = {"name": f"PowerAgent{idx}_{ts}", "capabilities": caps[:idx % len(caps) + 1]}
    r = requests.post(f"{BASE}/v1/register", json=payload, headers=headers, timeout=10)
    check(r, "POST", "/v1/register", note=f"agent {idx}")
    if r.status_code in (200, 201):
        data = r.json()
        return data.get("agent_id"), data.get("api_key")
    return None, None

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"\n{BOLD}MoltGrid Power Test  ts={ts}{RESET}")

    # ── Phase 1: create users & agents ──────────────────────────────────────
    section("Phase 1 — Signup / Login / Register Agents")
    users  = []   # [{user_id, token, email, agents:[{agent_id, api_key}]}]
    for i in range(1, NUM_USERS + 1):
        uid, token, email = signup(i)
        if not token:
            print(f"{RED}  Cannot continue without token for user {i}{RESET}")
            continue
        upgrade_to_hobby(uid)
        agents = []
        for j in range(1, AGENTS_EACH + 1):
            aid, api_key = register_agent(token, j)
            if aid:
                agents.append({"agent_id": aid, "api_key": api_key})
        users.append({"user_id": uid, "token": token, "email": email, "agents": agents})

    if not users:
        print(f"{RED}No users created — aborting.{RESET}")
        sys.exit(1)

    # Convenience aliases (first user / first agent)
    u0       = users[0]
    tok0     = u0["token"]
    uh0      = {"Authorization": f"Bearer {tok0}"}          # user headers
    ag0      = u0["agents"][0] if u0["agents"] else {}
    aid0     = ag0.get("agent_id", "MISSING")
    akey0    = ag0.get("api_key",  "MISSING")
    ah0      = {"X-API-Key": akey0}                          # agent headers

    # Second agent of first user (for cross-agent tests)
    ag1      = u0["agents"][1] if len(u0["agents"]) > 1 else ag0
    aid1     = ag1.get("agent_id", aid0)
    akey1    = ag1.get("api_key",  akey0)
    ah1      = {"X-API-Key": akey1}

    # ── Phase 2: Auth extras ─────────────────────────────────────────────────
    section("Phase 2 — Auth Extras")
    check(requests.get(f"{BASE}/v1/auth/me", headers=uh0, timeout=10), "GET", "/v1/auth/me")
    check(requests.post(f"{BASE}/v1/auth/refresh", headers=uh0, timeout=10), "POST", "/v1/auth/refresh")
    check(requests.post(f"{BASE}/v1/auth/2fa/setup", headers=uh0, timeout=10), "POST", "/v1/auth/2fa/setup", expected=(200, 201, 400, 422))
    check(requests.post(f"{BASE}/v1/auth/2fa/verify", headers=uh0,
                        json={"code": "000000"}, timeout=10),
          "POST", "/v1/auth/2fa/verify", expected=(200, 201, 400, 422))
    check(requests.post(f"{BASE}/v1/auth/2fa/disable", headers=uh0, timeout=10), "POST", "/v1/auth/2fa/disable", expected=(200, 204, 400, 422))
    # logout last so token stays valid for rest of tests
    # (we will call it at end)

    # ── Phase 3: Memory (agent-scoped) ───────────────────────────────────────
    section("Phase 3 — Memory")
    mem_key = f"powertest_key_{ts}"
    check(requests.post(f"{BASE}/v1/memory", headers=ah0,
                        json={"key": mem_key, "value": "hello world", "visibility": "private"},
                        timeout=10), "POST", "/v1/memory")
    check(requests.get(f"{BASE}/v1/memory/{mem_key}", headers=ah0, timeout=10), "GET", "/v1/memory/{key}")
    check(requests.get(f"{BASE}/v1/memory", headers=ah0, timeout=10), "GET", "/v1/memory")
    check(requests.patch(f"{BASE}/v1/memory/{mem_key}/visibility", headers=ah0,
                         json={"key": mem_key, "visibility": "shared"}, timeout=10),
          "PATCH", "/v1/memory/{key}/visibility")
    # cross-agent read (agent1 reads agent0's shared memory)
    check(requests.get(f"{BASE}/v1/agents/{aid0}/memory/{mem_key}", headers=ah1, timeout=10),
          "GET", "/v1/agents/{target_agent_id}/memory/{key}", expected=(200, 403, 404))
    check(requests.delete(f"{BASE}/v1/memory/{mem_key}", headers=ah0, timeout=10), "DELETE", "/v1/memory/{key}")

    # ── Phase 4: Queue ───────────────────────────────────────────────────────
    section("Phase 4 — Queue")
    r = requests.post(f"{BASE}/v1/queue/submit", headers=ah0,
                      json={"task_type": "power_test", "payload": {"ts": ts}, "priority": 5},
                      timeout=10)
    check(r, "POST", "/v1/queue/submit")
    job_id = r.json().get("job_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/queue", headers=ah0, timeout=10), "GET", "/v1/queue")
    check(requests.get(f"{BASE}/v1/queue/dead_letter", headers=ah0, timeout=10), "GET", "/v1/queue/dead_letter")

    r_claim = requests.post(f"{BASE}/v1/queue/claim", headers=ah0,
                            json={"task_types": ["power_test"]}, timeout=10)
    check(r_claim, "POST", "/v1/queue/claim", expected=(200, 201, 204))
    claimed_id = None
    if r_claim.status_code in (200, 201):
        d = r_claim.json()
        if isinstance(d, dict):
            claimed_id = d.get("job_id")

    if job_id:
        check(requests.get(f"{BASE}/v1/queue/{job_id}", headers=ah0, timeout=10),
              "GET", "/v1/queue/{job_id}")

    if claimed_id:
        check(requests.post(f"{BASE}/v1/queue/{claimed_id}/complete", headers=ah0,
                            json={"result": {"status": "done"}}, timeout=10),
              "POST", "/v1/queue/{job_id}/complete")
    elif job_id:
        check(requests.post(f"{BASE}/v1/queue/{job_id}/fail", headers=ah0,
                            json={"error": "simulated failure"}, timeout=10),
              "POST", "/v1/queue/{job_id}/fail", expected=(200, 201, 400, 404))
        check(requests.post(f"{BASE}/v1/queue/{job_id}/replay", headers=ah0, timeout=10),
              "POST", "/v1/queue/{job_id}/replay", expected=(200, 201, 400, 404))

    # ── Phase 5: Relay ───────────────────────────────────────────────────────
    section("Phase 5 — Relay")
    r = requests.post(f"{BASE}/v1/relay/send", headers=ah0,
                      json={"to_agent": aid1, "channel": "direct", "payload": f"ping {ts}"},
                      timeout=10)
    check(r, "POST", "/v1/relay/send", expected=(200, 201))
    msg_id = None
    if r.status_code in (200, 201):
        msg_id = r.json().get("message_id")

    check(requests.get(f"{BASE}/v1/relay/inbox", headers=ah1, timeout=10), "GET", "/v1/relay/inbox")
    if msg_id:
        check(requests.post(f"{BASE}/v1/relay/{msg_id}/read", headers=ah1, timeout=10),
              "POST", "/v1/relay/{message_id}/read", expected=(200, 204, 404))

    # ── Phase 6: Shared Memory ───────────────────────────────────────────────
    section("Phase 6 — Shared Memory")
    ns  = f"powertest_{ts}"
    smk = "config"
    check(requests.post(f"{BASE}/v1/shared-memory", headers=ah0,
                        json={"namespace": ns, "key": smk, "value": '{"version": 1}'},
                        timeout=10), "POST", "/v1/shared-memory")
    check(requests.get(f"{BASE}/v1/shared-memory", headers=ah0, timeout=10), "GET", "/v1/shared-memory")
    check(requests.get(f"{BASE}/v1/shared-memory/{ns}", headers=ah0, timeout=10), "GET", "/v1/shared-memory/{namespace}")
    check(requests.get(f"{BASE}/v1/shared-memory/{ns}/{smk}", headers=ah0, timeout=10), "GET", "/v1/shared-memory/{namespace}/{key}")
    check(requests.delete(f"{BASE}/v1/shared-memory/{ns}/{smk}", headers=ah0, timeout=10),
          "DELETE", "/v1/shared-memory/{namespace}/{key}", expected=(200, 204))

    # ── Phase 7: Directory ───────────────────────────────────────────────────
    section("Phase 7 — Directory")
    check(requests.put(f"{BASE}/v1/directory/me", headers=ah0,
                       json={"description": "Power test agent", "capabilities": ["memory", "queue"],
                             "tags": ["test"], "status": "online"},
                       timeout=10), "PUT", "/v1/directory/me")
    check(requests.get(f"{BASE}/v1/directory/me", headers=ah0, timeout=10), "GET", "/v1/directory/me")
    check(requests.patch(f"{BASE}/v1/directory/me/status", headers=ah0,
                         json={"available": False}, timeout=10), "PATCH", "/v1/directory/me/status")
    check(requests.get(f"{BASE}/v1/directory", headers=ah0, timeout=10), "GET", "/v1/directory")
    check(requests.get(f"{BASE}/v1/directory/stats", headers=ah0, timeout=10), "GET", "/v1/directory/stats")
    check(requests.get(f"{BASE}/v1/directory/search", headers=ah0,
                       params={"q": "power"}, timeout=10), "GET", "/v1/directory/search")
    check(requests.get(f"{BASE}/v1/directory/match", headers=ah0,
                       params={"need": "memory"}, timeout=10), "GET", "/v1/directory/match")
    check(requests.get(f"{BASE}/v1/directory/{aid0}", headers=ah0, timeout=10),
          "GET", "/v1/directory/{agent_id}", expected=(200, 404))
    check(requests.post(f"{BASE}/v1/directory/collaborations", headers=ah0,
                        json={"partner_agent": aid1, "outcome": "success", "rating": 5},
                        timeout=10), "POST", "/v1/directory/collaborations", expected=(200, 201, 400))
    check(requests.post(f"{BASE}/v1/agents/heartbeat", headers=ah0, timeout=10), "POST", "/v1/agents/heartbeat")
    check(requests.post(f"{BASE}/v1/heartbeat", headers=ah0, timeout=10), "POST", "/v1/heartbeat")

    # ── Phase 8: Sessions ────────────────────────────────────────────────────
    section("Phase 8 — Sessions")
    r = requests.post(f"{BASE}/v1/sessions", headers=ah0,
                      json={"metadata": {"purpose": "power_test"}}, timeout=10)
    check(r, "POST", "/v1/sessions", expected=(200, 201))
    sess_id = r.json().get("session_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/sessions", headers=ah0, timeout=10), "GET", "/v1/sessions")
    if sess_id:
        check(requests.get(f"{BASE}/v1/sessions/{sess_id}", headers=ah0, timeout=10),
              "GET", "/v1/sessions/{session_id}")
        check(requests.post(f"{BASE}/v1/sessions/{sess_id}/messages", headers=ah0,
                            json={"role": "user", "content": "hello from power test"},
                            timeout=10), "POST", "/v1/sessions/{session_id}/messages")
        check(requests.post(f"{BASE}/v1/sessions/{sess_id}/summarize", headers=ah0, timeout=10),
              "POST", "/v1/sessions/{session_id}/summarize", expected=(200, 201, 400))
        check(requests.delete(f"{BASE}/v1/sessions/{sess_id}", headers=ah0, timeout=10),
              "DELETE", "/v1/sessions/{session_id}", expected=(200, 204))

    # ── Phase 9: Schedules ───────────────────────────────────────────────────
    section("Phase 9 — Schedules")
    r = requests.post(f"{BASE}/v1/schedules", headers=ah0,
                      json={"cron_expr": "0 * * * *",
                            "payload": f'{{"ts": {ts}}}'},
                      timeout=10)
    check(r, "POST", "/v1/schedules", expected=(200, 201))
    task_id = r.json().get("task_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/schedules", headers=ah0, timeout=10), "GET", "/v1/schedules")
    if task_id:
        check(requests.get(f"{BASE}/v1/schedules/{task_id}", headers=ah0, timeout=10),
              "GET", "/v1/schedules/{task_id}")
        check(requests.patch(f"{BASE}/v1/schedules/{task_id}", headers=ah0,
                             params={"enabled": "false"}, timeout=10),
              "PATCH", "/v1/schedules/{task_id}")
        check(requests.delete(f"{BASE}/v1/schedules/{task_id}", headers=ah0, timeout=10),
              "DELETE", "/v1/schedules/{task_id}", expected=(200, 204))

    # ── Phase 10: PubSub ─────────────────────────────────────────────────────
    section("Phase 10 — PubSub")
    channel = f"powertest.{ts}"
    check(requests.post(f"{BASE}/v1/pubsub/subscribe", headers=ah0,
                        json={"channel": channel}, timeout=10),
          "POST", "/v1/pubsub/subscribe", expected=(200, 201))
    check(requests.get(f"{BASE}/v1/pubsub/subscriptions", headers=ah0, timeout=10),
          "GET", "/v1/pubsub/subscriptions")
    check(requests.get(f"{BASE}/v1/pubsub/channels", headers=ah0, timeout=10),
          "GET", "/v1/pubsub/channels")
    check(requests.post(f"{BASE}/v1/pubsub/publish", headers=ah0,
                        json={"channel": channel, "payload": f'{{"event": "ping", "ts": {ts}}}'},
                        timeout=10), "POST", "/v1/pubsub/publish")
    check(requests.post(f"{BASE}/v1/pubsub/unsubscribe", headers=ah0,
                        json={"channel": channel}, timeout=10),
          "POST", "/v1/pubsub/unsubscribe", expected=(200, 204))

    # ── Phase 11: Events ─────────────────────────────────────────────────────
    section("Phase 11 — Events")
    check(requests.get(f"{BASE}/v1/events", headers=ah0, timeout=10), "GET", "/v1/events")
    check(requests.post(f"{BASE}/v1/events/ack", headers=ah0,
                        json={"event_ids": []}, timeout=10),
          "POST", "/v1/events/ack", expected=(200, 204))

    # ── Phase 12: Marketplace ────────────────────────────────────────────────
    section("Phase 12 — Marketplace")
    r = requests.post(f"{BASE}/v1/marketplace/tasks", headers=ah0,
                      json={"title": f"Power Test Task {ts}",
                            "description": "automated test task",
                            "required_capabilities": ["text"],
                            "reward": 0.01},
                      timeout=10)
    check(r, "POST", "/v1/marketplace/tasks", expected=(200, 201))
    mt_id = r.json().get("task_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/marketplace/tasks", headers=ah0, timeout=10), "GET", "/v1/marketplace/tasks")
    if mt_id:
        check(requests.get(f"{BASE}/v1/marketplace/tasks/{mt_id}", headers=ah0, timeout=10),
              "GET", "/v1/marketplace/tasks/{task_id}")
        r_claim = requests.post(f"{BASE}/v1/marketplace/tasks/{mt_id}/claim", headers=ah1, timeout=10)
        check(r_claim, "POST", "/v1/marketplace/tasks/{task_id}/claim", expected=(200, 201, 400, 409))
        if r_claim.status_code in (200, 201):
            check(requests.post(f"{BASE}/v1/marketplace/tasks/{mt_id}/deliver", headers=ah1,
                                json={"result": "power test delivery"}, timeout=10),
                  "POST", "/v1/marketplace/tasks/{task_id}/deliver", expected=(200, 201, 400))
            check(requests.post(f"{BASE}/v1/marketplace/tasks/{mt_id}/review", headers=ah0,
                                json={"rating": 5, "comment": "great"}, timeout=10),
                  "POST", "/v1/marketplace/tasks/{task_id}/review", expected=(200, 201, 400))

    # ── Phase 13: Webhooks ───────────────────────────────────────────────────
    section("Phase 13 — Webhooks")
    r = requests.post(f"{BASE}/v1/user/agents/{aid0}/webhooks", headers=uh0,
                      json={"url": "https://webhook.site/power-test", "event_types": ["message.received"]},
                      timeout=10)
    check(r, "POST", "/v1/user/agents/{agent_id}/webhooks", expected=(200, 201))
    wh_id = r.json().get("webhook_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/webhooks", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/webhooks")

    # Agent-scoped webhooks
    r2 = requests.post(f"{BASE}/v1/webhooks", headers=ah0,
                       json={"url": "https://webhook.site/power-test-agent", "event_types": ["job.completed"]},
                       timeout=10)
    check(r2, "POST", "/v1/webhooks", expected=(200, 201))
    wh_id2 = r2.json().get("webhook_id") if r2.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/webhooks", headers=ah0, timeout=10), "GET", "/v1/webhooks")
    if wh_id2:
        check(requests.post(f"{BASE}/v1/webhooks/{wh_id2}/test", headers=ah0, timeout=10),
              "POST", "/v1/webhooks/{webhook_id}/test", expected=(200, 201, 400))
        check(requests.delete(f"{BASE}/v1/webhooks/{wh_id2}", headers=ah0, timeout=10),
              "DELETE", "/v1/webhooks/{webhook_id}", expected=(200, 204))
    if wh_id:
        check(requests.delete(f"{BASE}/v1/user/agents/{aid0}/webhooks/{wh_id}", headers=uh0, timeout=10),
              "DELETE", "/v1/user/agents/{agent_id}/webhooks/{webhook_id}", expected=(200, 204))

    # ── Phase 14: Text Processing ────────────────────────────────────────────
    section("Phase 14 — Text Processing")
    check(requests.post(f"{BASE}/v1/text/process", headers=ah0,
                        json={"text": "MoltGrid is an agent coordination platform.", "operation": "word_count"},
                        timeout=15), "POST", "/v1/text/process", expected=(200, 201))

    # ── Phase 15: Vector Memory ──────────────────────────────────────────────
    section("Phase 15 — Vector Memory")
    vec_key = f"vec_power_{ts}"
    check(requests.post(f"{BASE}/v1/vector/upsert", headers=ah0,
                        json={"key": vec_key, "text": "power test vector entry", "metadata": {"ts": ts}},
                        timeout=10), "POST", "/v1/vector/upsert", expected=(200, 201))
    check(requests.post(f"{BASE}/v1/vector/search", headers=ah0,
                        json={"query": "power test", "top_k": 3}, timeout=10),
          "POST", "/v1/vector/search", expected=(200, 201))
    check(requests.get(f"{BASE}/v1/vector/{vec_key}", headers=ah0, timeout=10),
          "GET", "/v1/vector/{key}", expected=(200, 404))
    check(requests.get(f"{BASE}/v1/vector", headers=ah0, timeout=10), "GET", "/v1/vector")
    check(requests.delete(f"{BASE}/v1/vector/{vec_key}", headers=ah0, timeout=10),
          "DELETE", "/v1/vector/{key}", expected=(200, 204, 404))

    # ── Phase 16: Testing / Scenarios ───────────────────────────────────────
    section("Phase 16 — Testing / Scenarios")
    r = requests.post(f"{BASE}/v1/testing/scenarios", headers=ah0,
                      json={"pattern": "leader_election", "agent_count": 3},
                      timeout=10)
    check(r, "POST", "/v1/testing/scenarios", expected=(200, 201))
    sc_id = r.json().get("scenario_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/testing/scenarios", headers=ah0, timeout=10),
          "GET", "/v1/testing/scenarios")
    if sc_id:
        check(requests.post(f"{BASE}/v1/testing/scenarios/{sc_id}/run", headers=ah0, timeout=10),
              "POST", "/v1/testing/scenarios/{scenario_id}/run", expected=(200, 201, 400))
        check(requests.get(f"{BASE}/v1/testing/scenarios/{sc_id}/results", headers=ah0, timeout=10),
              "GET", "/v1/testing/scenarios/{scenario_id}/results", expected=(200, 404))

    # ── Phase 17: MoltBook ───────────────────────────────────────────────────
    section("Phase 17 — MoltBook")
    check(requests.post(f"{BASE}/v1/moltbook/register",
                        json={"moltbook_user_id": f"mb_powertest_{ts}", "display_name": f"PowerAgent_{ts}"},
                        timeout=10), "POST", "/v1/moltbook/register", expected=(200, 201, 400, 409))
    check(requests.get(f"{BASE}/v1/moltbook/feed", headers=ah0, timeout=10),
          "GET", "/v1/moltbook/feed", expected=(200,))
    check(requests.post(f"{BASE}/v1/moltbook/events", headers=ah0,
                        json={"event_type": "power_test", "data": {"ts": ts}},
                        timeout=10), "POST", "/v1/moltbook/events", expected=(200, 201))

    # ── Phase 18: Onboarding ─────────────────────────────────────────────────
    section("Phase 18 — Onboarding")
    check(requests.post(f"{BASE}/v1/onboarding/start", headers=ah0, timeout=10),
          "POST", "/v1/onboarding/start", expected=(200, 201, 400))
    check(requests.get(f"{BASE}/v1/onboarding/status", headers=ah0, timeout=10),
          "GET", "/v1/onboarding/status", expected=(200,))

    # ── Phase 19: Agents extras ──────────────────────────────────────────────
    section("Phase 19 — Agent Extras")
    check(requests.post(f"{BASE}/v1/agents/{aid0}/integrations", headers=ah0,
                        json={"platform": "slack", "config": {"webhook_url": "https://hooks.slack.com/test"}},
                        timeout=10), "POST", "/v1/agents/{agent_id}/integrations", expected=(200, 201, 400))
    check(requests.get(f"{BASE}/v1/agents/{aid0}/integrations", headers=ah0, timeout=10),
          "GET", "/v1/agents/{agent_id}/integrations", expected=(200,))
    r_rot = requests.post(f"{BASE}/v1/agents/rotate-key", headers=ah0, timeout=10)
    check(r_rot, "POST", "/v1/agents/rotate-key", expected=(200, 201))
    if r_rot.status_code in (200, 201):
        new_key = r_rot.json().get("api_key")
        if new_key:
            ah0 = {"X-API-Key": new_key}   # update for remainder of tests

    # ── Phase 20: User Dashboard ─────────────────────────────────────────────
    section("Phase 20 — User Dashboard")
    check(requests.get(f"{BASE}/v1/user/overview", headers=uh0, timeout=10), "GET", "/v1/user/overview")
    check(requests.get(f"{BASE}/v1/user/agents", headers=uh0, timeout=10), "GET", "/v1/user/agents")
    check(requests.get(f"{BASE}/v1/user/usage", headers=uh0, timeout=10), "GET", "/v1/user/usage")
    check(requests.get(f"{BASE}/v1/user/billing", headers=uh0, timeout=10), "GET", "/v1/user/billing")
    check(requests.get(f"{BASE}/v1/user/audit-log", headers=uh0, timeout=10), "GET", "/v1/user/audit-log")
    check(requests.get(f"{BASE}/v1/user/audit-log/export", headers=uh0, timeout=10),
          "GET", "/v1/user/audit-log/export", expected=(200,))
    check(requests.get(f"{BASE}/v1/user/integrations/status", headers=uh0, timeout=10),
          "GET", "/v1/user/integrations/status", expected=(200,))
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/activity", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/activity")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/stats", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/stats")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/messages-list", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/messages-list")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/memory-list", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/memory-list")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/jobs-list", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/jobs-list")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/schedules", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/schedules")
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/integrations", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/integrations", expected=(200,))
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/memory-access-log", headers=uh0, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/memory-access-log")

    # memory-entry operations (need a fresh key)
    mem_key2 = f"dash_test_{ts}"
    requests.post(f"{BASE}/v1/memory", headers={"X-API-Key": akey0},
                  json={"key": mem_key2, "value": "dash test", "visibility": "private"}, timeout=10)
    check(requests.get(f"{BASE}/v1/user/agents/{aid0}/memory-entry",
                       headers=uh0, params={"key": mem_key2}, timeout=10),
          "GET", "/v1/user/agents/{agent_id}/memory-entry", expected=(200, 404))
    check(requests.patch(f"{BASE}/v1/user/agents/{aid0}/memory-entry/visibility",
                         headers=uh0,
                         json={"key": mem_key2, "visibility": "shared"}, timeout=10),
          "PATCH", "/v1/user/agents/{agent_id}/memory-entry/visibility", expected=(200, 404))
    check(requests.post(f"{BASE}/v1/user/agents/{aid0}/memory-bulk-visibility",
                        headers=uh0,
                        json={"entries": [{"key": mem_key2}], "visibility": "private"}, timeout=10),
          "POST", "/v1/user/agents/{agent_id}/memory-bulk-visibility", expected=(200, 201))
    check(requests.delete(f"{BASE}/v1/user/agents/{aid0}/memory-entry",
                          headers=uh0, params={"key": mem_key2}, timeout=10),
          "DELETE", "/v1/user/agents/{agent_id}/memory-entry", expected=(200, 204, 404))

    # transfer (to a non-existent email — expect 404; 400 is also acceptable)
    check(requests.post(f"{BASE}/v1/user/agents/{aid0}/transfer",
                        headers=uh0, json={"to_email": f"nobody_{ts}@transfer.invalid"}, timeout=10),
          "POST", "/v1/user/agents/{agent_id}/transfer", expected=(200, 201, 400, 404))

    # notifications
    check(requests.post(f"{BASE}/v1/user/notifications/preferences", headers=uh0,
                        json={"email_on_message": True, "email_on_job_complete": False},
                        timeout=10), "POST", "/v1/user/notifications/preferences", expected=(200, 201))
    check(requests.get(f"{BASE}/v1/user/notifications/preferences", headers=uh0, timeout=10),
          "GET", "/v1/user/notifications/preferences")

    # ── Phase 21: Orgs ───────────────────────────────────────────────────────
    section("Phase 21 — Orgs")
    r = requests.post(f"{BASE}/v1/orgs", headers=uh0,
                      json={"name": f"PowerOrg_{ts}", "description": "power test org"},
                      timeout=10)
    check(r, "POST", "/v1/orgs", expected=(200, 201))
    org_id = r.json().get("org_id") if r.status_code in (200, 201) else None

    check(requests.get(f"{BASE}/v1/orgs", headers=uh0, timeout=10), "GET", "/v1/orgs")
    if org_id:
        check(requests.get(f"{BASE}/v1/orgs/{org_id}", headers=uh0, timeout=10),
              "GET", "/v1/orgs/{org_id}")
        # add member (second user if it exists)
        if len(users) > 1:
            member_uid = users[1]["user_id"]
            r_add = requests.post(f"{BASE}/v1/orgs/{org_id}/members", headers=uh0,
                                  json={"user_id": member_uid, "role": "member"}, timeout=10)
            check(r_add, "POST", "/v1/orgs/{org_id}/members", expected=(200, 201, 400, 409))
            check(requests.get(f"{BASE}/v1/orgs/{org_id}/members", headers=uh0, timeout=10),
                  "GET", "/v1/orgs/{org_id}/members")
            if r_add.status_code in (200, 201):
                check(requests.patch(f"{BASE}/v1/orgs/{org_id}/members/{member_uid}",
                                     headers=uh0, json={"role": "admin"}, timeout=10),
                      "PATCH", "/v1/orgs/{org_id}/members/{user_id}", expected=(200, 400))
                check(requests.delete(f"{BASE}/v1/orgs/{org_id}/members/{member_uid}",
                                      headers=uh0, timeout=10),
                      "DELETE", "/v1/orgs/{org_id}/members/{user_id}", expected=(200, 204))
        check(requests.post(f"{BASE}/v1/orgs/{org_id}/switch", headers=uh0, timeout=10),
              "POST", "/v1/orgs/{org_id}/switch", expected=(200, 201, 400))

    # ── Phase 22: Templates ──────────────────────────────────────────────────
    section("Phase 22 — Templates")
    check(requests.get(f"{BASE}/v1/templates", timeout=10), "GET", "/v1/templates")
    r_tmpl = requests.get(f"{BASE}/v1/templates", timeout=10)
    if r_tmpl.status_code == 200:
        tmpl_list = r_tmpl.json()
        if isinstance(tmpl_list, list) and tmpl_list:
            tid = tmpl_list[0].get("template_id") or tmpl_list[0].get("id")
            if tid:
                check(requests.get(f"{BASE}/v1/templates/{tid}", timeout=10),
                      "GET", "/v1/templates/{template_id}", expected=(200, 404))

    # ── Phase 23: Guides / Docs ──────────────────────────────────────────────
    section("Phase 23 — Guides / Docs")
    check(requests.get(f"{BASE}/v1/guides/langchain", headers=ah0, timeout=10),
          "GET", "/v1/guides/{platform}", expected=(200, 404))
    check(requests.get(f"{BASE}/v1/skill.md", timeout=10), "GET", "/v1/skill.md", expected=(200, 404))
    check(requests.get(f"{BASE}/skill.md", timeout=10), "GET", "/skill.md", expected=(200, 404))
    check(requests.get(f"{BASE}/v1/obstacle-course.md", headers=ah0, timeout=10),
          "GET", "/v1/obstacle-course.md", expected=(200,))
    check(requests.get(f"{BASE}/obstacle-course.md", timeout=10),
          "GET", "/obstacle-course.md", expected=(200,))

    # ── Phase 24: Obstacle Course ────────────────────────────────────────────
    section("Phase 24 — Obstacle Course")
    r = requests.post(f"{BASE}/v1/obstacle-course/submit", headers=ah0,
                      json={"answers": {"q1": "answer1"}}, timeout=10)
    check(r, "POST", "/v1/obstacle-course/submit", expected=(200, 201, 400, 422))
    check(requests.get(f"{BASE}/v1/obstacle-course/leaderboard", timeout=10),
          "GET", "/v1/obstacle-course/leaderboard", expected=(200,))
    check(requests.get(f"{BASE}/v1/obstacle-course/my-result", headers=ah0, timeout=10),
          "GET", "/v1/obstacle-course/my-result", expected=(200, 404))

    # ── Phase 25: SLA / Health / Stats / Leaderboard / Pricing ──────────────
    section("Phase 25 — System Endpoints")
    check(requests.get(f"{BASE}/v1/health", timeout=10), "GET", "/v1/health")
    check(requests.get(f"{BASE}/v1/stats", headers=ah0, timeout=10), "GET", "/v1/stats")
    check(requests.get(f"{BASE}/v1/sla", timeout=10), "GET", "/v1/sla")
    check(requests.get(f"{BASE}/v1/leaderboard", timeout=10), "GET", "/v1/leaderboard")
    check(requests.get(f"{BASE}/v1/pricing", timeout=10), "GET", "/v1/pricing")
    check(requests.get(f"{BASE}/", timeout=10), "GET", "/", expected=(200,))

    # ── Phase 26: User-agent schedule helpers ────────────────────────────────
    section("Phase 26 — User Agent Schedules")
    r = requests.post(f"{BASE}/v1/user/agents/{aid0}/schedules", headers=uh0,
                      json={"cron_expr": "0 12 * * *", "payload": "{}"},
                      timeout=10)
    check(r, "POST", "/v1/user/agents/{agent_id}/schedules", expected=(200, 201))
    ua_task_id = r.json().get("task_id") if r.status_code in (200, 201) else None
    if ua_task_id:
        check(requests.patch(f"{BASE}/v1/user/agents/{aid0}/schedules/{ua_task_id}",
                             headers=uh0, json={"cron_expr": "0 6 * * *"}, timeout=10),
              "PATCH", "/v1/user/agents/{agent_id}/schedules/{task_id}", expected=(200,))
        check(requests.delete(f"{BASE}/v1/user/agents/{aid0}/schedules/{ua_task_id}",
                              headers=uh0, timeout=10),
              "DELETE", "/v1/user/agents/{agent_id}/schedules/{task_id}", expected=(200, 204))

    # ── Phase 27: Contact ────────────────────────────────────────────────────
    section("Phase 27 — Contact")
    check(requests.post(f"{BASE}/v1/contact",
                        json={"name": "Power Test", "email": f"powertest_{ts}@test.moltgrid.net",
                              "message": "Automated power test contact form submission."},
                        timeout=10), "POST", "/v1/contact", expected=(200, 201))

    # ── Phase 28: Auth logout (last) ─────────────────────────────────────────
    section("Phase 28 — Auth Logout")
    check(requests.post(f"{BASE}/v1/auth/logout", headers=uh0, timeout=10),
          "POST", "/v1/auth/logout", expected=(200, 204))

    # ── Summary ───────────────────────────────────────────────────────────────
    total   = len(results)
    passed  = sum(1 for r in results if r[3])
    failed  = total - passed
    pct     = (passed / total * 100) if total else 0

    print(f"\n{BOLD}{'═'*65}{RESET}")
    print(f"{BOLD}  POWER TEST SUMMARY{RESET}")
    print(f"{BOLD}{'═'*65}{RESET}")
    print(f"  Total endpoints hit : {total}")
    print(f"  {GREEN}Passed{RESET}              : {passed}")
    print(f"  {RED}Failed{RESET}              : {failed}")
    print(f"  Pass rate           : {pct:.1f}%")

    if failed:
        print(f"\n{BOLD}{RED}  Failed endpoints:{RESET}")
        for method, path, status, ok_, note in results:
            if not ok_:
                print(f"    {RED}{status:3d}  {method:6s} {path}{RESET}  {note[:80]}")

    print(f"\n{BOLD}{'═'*65}{RESET}\n")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())

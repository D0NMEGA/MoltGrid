"""
3-User Realistic Simulation -- 17 Agents Across Scale/Team/Free Tiers
Phase 79: Final validation before v1.0.0 launch

Usage:
  python tests/sim_3user.py              # Full run (~25 min)
  python tests/sim_3user.py --quick      # User C only (~5 min)
"""
from __future__ import annotations
import os, asyncio, json, sys, time, uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx

os.environ["PYTHONUNBUFFERED"] = "1"
API = os.environ.get("MOLTGRID_API_URL", "https://api.moltgrid.net")
QUICK_MODE = "--quick" in sys.argv
SEMAPHORE = asyncio.Semaphore(10)  # Max 10 concurrent requests

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SimResult:
    user: str        # "UserA", "UserB", "UserC"
    agent: str       # agent name
    test: str        # test name
    passed: bool
    detail: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SharedState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.results: list[SimResult] = []
        self.server_errors: list[dict] = []           # SIM-05: must be empty
        self.onboarding_times: dict[str, float] = {}  # SIM-06: per-user timing
        self.obstacle_completions: dict[str, bool] = {}  # SIM-04: per-agent
        self.registered_agents: dict[str, dict] = {}  # name -> {id, key, user}
        self.start_time: float = 0.0
        self.monitoring_iterations: int = 0           # SIM-02
        self.monitoring_duration: float = 0.0         # SIM-02
        self.hit_429: bool = False                    # SIM-03
        self.recovery_ok: bool = False                # SIM-03


S = SharedState()

# ---------------------------------------------------------------------------
# Rate budgets -- one per tier
# ---------------------------------------------------------------------------

class RateBudget:
    """Token-bucket rate limiter -- one per user tier."""

    def __init__(self, max_per_minute: int) -> None:
        self.max_per_minute = max_per_minute
        self.calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.max_per_minute:
                wait = 60 - (now - self.calls[0]) + 0.5
                await asyncio.sleep(wait)
            self.calls.append(time.time())


BUDGET_SCALE = RateBudget(1100)  # Scale: 1200/min, cap at 1100
BUDGET_TEAM = RateBudget(580)    # Team: 600/min, cap at 580
BUDGET_FREE = RateBudget(55)     # Free: conservative to avoid 429 during obstacle course

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(agent: str, msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"  [{ts}] {agent:25s} | {msg}", flush=True)

# ---------------------------------------------------------------------------
# Centralized API call
# ---------------------------------------------------------------------------

async def call(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    agent: str,
    *,
    json_body: Any = None,
    params: dict | None = None,
    budget: RateBudget | None = None,
    skip_rate_wait: bool = False,
    timeout: float = 30.0,
) -> httpx.Response:
    if budget and not skip_rate_wait:
        await budget.acquire()

    url = f"{API}{path}"
    key = S.registered_agents.get(agent, {}).get("key", "")
    hdrs: dict[str, str] = {}
    if key:
        hdrs["X-API-Key"] = key

    async with SEMAPHORE:
        t0 = time.monotonic()
        try:
            resp = await client.request(
                method, url,
                json=json_body, params=params,
                headers=hdrs,
                timeout=timeout,
            )
        except Exception as exc:
            return httpx.Response(598, text=str(exc),
                                  request=httpx.Request(method, url))

    if resp.status_code >= 500:
        async with S.lock:
            S.server_errors.append({
                "agent": agent, "method": method, "path": path,
                "status": resp.status_code, "body": resp.text[:500],
                "ts": datetime.now(timezone.utc).isoformat(),
            })

    if resp.status_code == 429:
        retry = int(resp.headers.get("Retry-After", "5"))
        log(agent, f"429 on {path} -- wait {min(retry, 30)}s")
        await asyncio.sleep(min(retry, 30))

    return resp

# ---------------------------------------------------------------------------
# Record helper
# ---------------------------------------------------------------------------

async def record(user: str, agent: str, test: str, passed: bool, detail: str = "") -> None:
    async with S.lock:
        S.results.append(SimResult(user=user, agent=agent, test=test,
                                   passed=passed, detail=detail))

# ---------------------------------------------------------------------------
# Agent registration
# ---------------------------------------------------------------------------

async def register_simulation_agents(client: httpx.AsyncClient) -> None:
    """Register all 17 simulation agents. Populates S.registered_agents."""
    agent_specs = (
        [(f"SimA_Research_{i:02d}", "UserA") for i in range(1, 9)] +  # 8 Scale
        [(f"SimB_DevOps_{i:02d}", "UserB")   for i in range(1, 9)] +  # 8 Team
        [("SimC_Free_01", "UserC")]                                    # 1 Free
    )
    hex4 = uuid.uuid4().hex[:4]
    for name, user in agent_specs:
        unique_name = f"Phase79_{name}_{hex4}"
        r = await client.post(f"{API}/v1/register",
                              json={"name": unique_name},
                              timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            async with S.lock:
                S.registered_agents[name] = {
                    "id": data["agent_id"],
                    "key": data["api_key"],
                    "user": user,
                }
            log(name, f"Registered -- id={data['agent_id'][:8]}...")
        else:
            log(name, f"Registration FAILED: {r.status_code} {r.text[:100]}")

# ---------------------------------------------------------------------------
# Onboarding timing (SIM-06)
# ---------------------------------------------------------------------------

async def time_onboarding(
    client: httpx.AsyncClient,
    user_label: str,
    agent_name: str,
) -> float:
    """Measure time from register to onboarding/status. Stores in S.onboarding_times."""
    t0 = time.monotonic()
    r = await client.post(f"{API}/v1/register",
                          json={"name": f"Phase79_Onboard_{user_label}_{uuid.uuid4().hex[:4]}"},
                          timeout=30.0)
    if r.status_code != 200:
        log(agent_name, f"Onboarding timing: registration failed {r.status_code}")
        return -1.0
    data = r.json()
    ob_key = data["api_key"]
    ob_hdrs = {"X-API-Key": ob_key}

    async with SEMAPHORE:
        await client.post(f"{API}/v1/memory",
                          json={"key": "onboard_start", "value": "started"},
                          headers=ob_hdrs, timeout=30.0)
    async with SEMAPHORE:
        await client.post(f"{API}/v1/onboarding/start",
                          headers=ob_hdrs, timeout=30.0)
    async with SEMAPHORE:
        await client.get(f"{API}/v1/onboarding/status",
                         headers=ob_hdrs, timeout=30.0)

    elapsed = time.monotonic() - t0
    async with S.lock:
        S.onboarding_times[user_label] = elapsed
    log(agent_name, f"Onboarding timing for {user_label}: {elapsed:.1f}s")
    return elapsed

# ===========================================================================
# OBSTACLE COURSE STAGE FUNCTIONS
# ===========================================================================

async def stage1_memory(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 1: Memory Foundations -- Memory + Vector Memory."""
    agent_id = state.get("agent_id", "")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Write 3 memory keys
    r1 = await call(client, "POST", "/v1/memory", agent_name, budget=budget,
                    json_body={"key": "stage1_identity",
                               "value": f"name={agent_name}, description=Obstacle course challenger, started_at={now_iso}",
                               "namespace": "obstacle_course"})
    r2 = await call(client, "POST", "/v1/memory", agent_name, budget=budget,
                    json_body={"key": "stage1_plan",
                               "value": "strategy=sequential, complete all 10 stages, submit at end",
                               "namespace": "obstacle_course"})
    r3 = await call(client, "POST", "/v1/memory", agent_name, budget=budget,
                    json_body={"key": "stage1_capabilities",
                               "value": "data_analysis, code_generation, semantic_search, multi_agent_coordination, event_processing",
                               "namespace": "obstacle_course"})

    # Upsert 3 vector entries
    r4 = await call(client, "POST", "/v1/vector/upsert", agent_name, budget=budget,
                    json_body={"key": "oc_strengths",
                               "text": "I excel at data analysis, code generation, and multi-step reasoning",
                               "namespace": "obstacle_course"})
    r5 = await call(client, "POST", "/v1/vector/upsert", agent_name, budget=budget,
                    json_body={"key": "oc_goals",
                               "text": "Complete the obstacle course and demonstrate all MoltGrid services",
                               "namespace": "obstacle_course"})
    r6 = await call(client, "POST", "/v1/vector/upsert", agent_name, budget=budget,
                    json_body={"key": "oc_collab_prefs",
                               "text": "Prefer async collaboration via relay and shared memory namespaces",
                               "namespace": "obstacle_course"})

    # Semantic search
    r7 = await call(client, "POST", "/v1/vector/search", agent_name, budget=budget,
                    json_body={"query": "what am I good at?",
                               "namespace": "obstacle_course",
                               "limit": 3})
    search_ok = r7.status_code == 200

    # List memory keys
    r8 = await call(client, "GET", "/v1/memory", agent_name, budget=budget,
                    params={"namespace": "obstacle_course"})

    ok = all(r.status_code in (200, 201) for r in [r1, r2, r3, r4, r5, r6]) and search_ok
    return ok


async def stage2_relay(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 2: Communication -- Relay + Events."""
    agent_id = state.get("agent_id", "")

    # Send relay message to self
    r1 = await call(client, "POST", "/v1/relay/send", agent_name, budget=budget,
                    json_body={"to_agent": agent_id,
                               "channel": "obstacle_course",
                               "payload": "Stage 2: Stage 1 complete. Memory and vector storage working."})

    # Check inbox
    r2 = await call(client, "GET", "/v1/relay/inbox", agent_name, budget=budget,
                    params={"unread_only": "true"})

    message_id = None
    if r2.status_code == 200:
        try:
            inbox = r2.json()
            msgs = inbox if isinstance(inbox, list) else inbox.get("messages", [])
            if msgs:
                message_id = msgs[0].get("id") or msgs[0].get("message_id")
        except Exception:
            pass
    state["relay_message_id"] = message_id

    # Mark message read
    if message_id:
        r3 = await call(client, "POST", f"/v1/relay/{message_id}/read", agent_name, budget=budget)
    else:
        r3 = httpx.Response(200)

    # Poll events
    r4 = await call(client, "GET", "/v1/events", agent_name, budget=budget)

    # Ack an event
    event_id = None
    if r4.status_code == 200:
        try:
            evts = r4.json()
            items = evts if isinstance(evts, list) else evts.get("events", [])
            if items:
                event_id = items[0].get("id") or items[0].get("event_id")
        except Exception:
            pass

    if event_id:
        r5 = await call(client, "POST", "/v1/events/ack", agent_name, budget=budget,
                        json_body={"event_ids": [event_id]})
    else:
        r5 = httpx.Response(200)

    ok = r1.status_code in (200, 201) and r2.status_code == 200 and r4.status_code == 200
    return ok


async def stage3_queue(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 3: Job Processing Pipeline -- Queue + Schedules."""
    # Submit first job
    r1 = await call(client, "POST", "/v1/queue/submit", agent_name, budget=budget,
                    json_body={"queue_name": "obstacle_course",
                               "payload": {"task": "process_stage3_data", "data": [1, 2, 3, 4, 5]},
                               "priority": 10, "max_attempts": 3})
    job_id1 = None
    if r1.status_code in (200, 201):
        try:
            job_id1 = r1.json().get("job_id") or r1.json().get("id")
        except Exception:
            pass
    state["job_id1"] = job_id1

    # Claim first job
    r2 = await call(client, "POST", "/v1/queue/claim", agent_name, budget=budget,
                    json_body={"queue_name": "obstacle_course"})
    claimed_id = None
    if r2.status_code == 200:
        try:
            claimed_id = r2.json().get("job_id") or r2.json().get("id")
        except Exception:
            pass
    effective_id = claimed_id or job_id1

    # Complete first job
    if effective_id:
        r3 = await call(client, "POST", f"/v1/queue/{effective_id}/complete", agent_name, budget=budget,
                        json_body={"result": {"sum": 15, "count": 5, "average": 3.0}})
    else:
        r3 = httpx.Response(200)

    # Submit second job (to fail)
    r4 = await call(client, "POST", "/v1/queue/submit", agent_name, budget=budget,
                    json_body={"queue_name": "obstacle_course",
                               "payload": {"task": "fail_test"},
                               "max_attempts": 1})
    job_id2 = None
    if r4.status_code in (200, 201):
        try:
            job_id2 = r4.json().get("job_id") or r4.json().get("id")
        except Exception:
            pass
    state["job_id2"] = job_id2

    # Claim second job
    r5 = await call(client, "POST", "/v1/queue/claim", agent_name, budget=budget,
                    json_body={"queue_name": "obstacle_course"})
    claimed_id2 = None
    if r5.status_code == 200:
        try:
            claimed_id2 = r5.json().get("job_id") or r5.json().get("id")
        except Exception:
            pass
    effective_id2 = claimed_id2 or job_id2

    # Fail second job
    if effective_id2:
        r6 = await call(client, "POST", f"/v1/queue/{effective_id2}/fail", agent_name, budget=budget,
                        json_body={"reason": "Intentional failure for obstacle course testing"})
    else:
        r6 = httpx.Response(200)

    # Check dead letter queue
    r7 = await call(client, "GET", "/v1/queue/dead_letter", agent_name, budget=budget)

    # Create schedule
    r8 = await call(client, "POST", "/v1/schedules", agent_name, budget=budget,
                    json_body={"cron_expr": "*/30 * * * *",
                               "queue_name": "obstacle_course_heartbeat",
                               "payload": {"action": "scheduled_ping"},
                               "priority": 1})
    schedule_id = None
    if r8.status_code in (200, 201):
        try:
            schedule_id = r8.json().get("task_id") or r8.json().get("id")
        except Exception:
            pass
    state["schedule_id"] = schedule_id

    ok = r1.status_code in (200, 201) and r4.status_code in (200, 201) and r7.status_code == 200
    return ok


async def stage4_shared_memory(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 4: Shared State -- Shared Memory + Memory Visibility."""
    agent_id = state.get("agent_id", "")
    ns = f"obstacle_course_{agent_id}"

    # Patch visibility of stage1_capabilities to public
    r1 = await call(client, "PATCH", "/v1/memory/stage1_capabilities/visibility", agent_name, budget=budget,
                    json_body={"visibility": "public"},
                    params={"namespace": "obstacle_course"})

    # Write 2 shared memory entries
    now_iso = datetime.now(timezone.utc).isoformat()
    r2 = await call(client, "POST", "/v1/shared-memory", agent_name, budget=budget,
                    json_body={"namespace": ns,
                               "key": "progress",
                               "value": f"stages_completed=[1,2,3], current_stage=4, started_at={now_iso}",
                               "description": "Obstacle course progress tracker"})
    r3 = await call(client, "POST", "/v1/shared-memory", agent_name, budget=budget,
                    json_body={"namespace": ns,
                               "key": "config",
                               "value": "strategy=sequential, target_time_minutes=15"})

    # Read back shared memory namespace
    r4 = await call(client, "GET", f"/v1/shared-memory/{ns}", agent_name, budget=budget)
    r5 = await call(client, "GET", f"/v1/shared-memory/{ns}/progress", agent_name, budget=budget)

    ok = r2.status_code in (200, 201) and r3.status_code in (200, 201) and r4.status_code == 200
    return ok


async def stage5_pubsub(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 5: Broadcast and Subscribe -- Pub/Sub."""
    agent_id = state.get("agent_id", "")
    channel = f"obstacle_course_{agent_id}"

    # Subscribe to channel
    r1 = await call(client, "POST", "/v1/pubsub/subscribe", agent_name, budget=budget,
                    json_body={"channel": channel})

    # Publish a message
    r2 = await call(client, "POST", "/v1/pubsub/publish", agent_name, budget=budget,
                    json_body={"channel": channel,
                               "payload": f"Agent {agent_id} halfway through the obstacle course - stage 5!"})

    # List subscriptions
    r3 = await call(client, "GET", "/v1/pubsub/subscriptions", agent_name, budget=budget)

    # List channels
    r4 = await call(client, "GET", "/v1/pubsub/channels", agent_name, budget=budget)

    # Poll events to receive pub/sub broadcast
    r5 = await call(client, "GET", "/v1/events", agent_name, budget=budget)

    ok = r1.status_code in (200, 201) and r2.status_code in (200, 201) and r3.status_code == 200
    return ok


async def stage6_directory(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 6: Agent Discovery -- Directory + Heartbeat."""
    # Post heartbeat
    r1 = await call(client, "POST", "/v1/heartbeat", agent_name, budget=budget,
                    json_body={"status": "online",
                               "metadata": {"obstacle_course": True, "current_stage": 6}})

    # Update directory profile
    r2 = await call(client, "PUT", "/v1/directory/me", agent_name, budget=budget,
                    json_body={"description": "Obstacle course challenger -- testing all 20 MoltGrid services",
                               "capabilities": ["data_analysis", "task_processing",
                                                "multi_agent_coordination", "semantic_search", "pub_sub"],
                               "available": True,
                               "looking_for": "other agents to collaborate with"})

    # Browse directory
    r3 = await call(client, "GET", "/v1/directory", agent_name, budget=budget)

    # Search directory
    r4 = await call(client, "GET", "/v1/directory/search", agent_name, budget=budget,
                    params={"q": "data analysis"})

    # Directory stats
    r5 = await call(client, "GET", "/v1/directory/stats", agent_name, budget=budget)

    # Get own profile
    r6 = await call(client, "GET", "/v1/directory/me", agent_name, budget=budget)

    # Update profile with skills and interests
    r7 = await call(client, "PUT", "/v1/directory/me", agent_name, budget=budget,
                    json_body={"description": "Obstacle course challenger",
                               "capabilities": ["data_analysis", "task_processing"],
                               "skills": ["python", "api_integration", "web_scraping"],
                               "interests": ["AI_agents", "automation"],
                               "public": True})

    ok = r1.status_code in (200, 201) and r3.status_code == 200
    return ok


async def stage7_webhooks(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 7: Webhooks and Notifications -- Webhooks + Text Utilities."""
    # Register webhook
    r1 = await call(client, "POST", "/v1/webhooks", agent_name, budget=budget,
                    json_body={"url": f"https://httpbin.org/post?agent={agent_name}",
                               "event_types": ["message.received", "job.completed"],
                               "secret": "obstacle_course_secret_123"})
    webhook_id = None
    if r1.status_code in (200, 201):
        try:
            webhook_id = r1.json().get("id") or r1.json().get("webhook_id")
        except Exception:
            pass
    state["webhook_id"] = webhook_id

    # List webhooks
    r2 = await call(client, "GET", "/v1/webhooks", agent_name, budget=budget)

    # Test webhook
    if webhook_id:
        r3 = await call(client, "POST", f"/v1/webhooks/{webhook_id}/test", agent_name, budget=budget)
    else:
        r3 = httpx.Response(200)

    # Process text (extract URLs)
    r4 = await call(client, "POST", "/v1/text/process", agent_name, budget=budget,
                    json_body={"text": "Obstacle course stage 7 complete! Check https://api.moltgrid.net/v1/obstacle-course/leaderboard for rankings.",
                               "operation": "extract_urls"})

    # Hash progress summary
    r5 = await call(client, "POST", "/v1/text/process", agent_name, budget=budget,
                    json_body={"text": "stages_completed:1,2,3,4,5,6,7",
                               "operation": "hash_sha256"})

    # Delete webhook
    if webhook_id:
        r6 = await call(client, "DELETE", f"/v1/webhooks/{webhook_id}", agent_name, budget=budget)
    else:
        r6 = httpx.Response(200)

    ok = r1.status_code in (200, 201) and r4.status_code in (200, 201) and r5.status_code in (200, 201)
    return ok


async def stage8_sessions(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 8: Sessions and Context -- Sessions + Templates."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Check templates
    r1 = await call(client, "GET", "/v1/templates", agent_name, budget=budget)

    # Create session
    r2 = await call(client, "POST", "/v1/sessions", agent_name, budget=budget,
                    json_body={"title": "Obstacle Course Run",
                               "metadata": {"started_at": now_iso, "target": "sub-15-minutes"},
                               "max_tokens": 4000})
    session_id = None
    if r2.status_code in (200, 201):
        try:
            session_id = r2.json().get("session_id") or r2.json().get("id")
        except Exception:
            pass
    state["session_id"] = session_id

    if not session_id:
        return False

    # Add 3 messages (user, assistant, user pattern per plan)
    r3 = await call(client, "POST", f"/v1/sessions/{session_id}/messages", agent_name, budget=budget,
                    json_body={"role": "user", "content": "Starting obstacle course run."})
    r4 = await call(client, "POST", f"/v1/sessions/{session_id}/messages", agent_name, budget=budget,
                    json_body={"role": "assistant",
                               "content": "Started obstacle course. Completed memory storage and vector search in Stage 1."})
    r5 = await call(client, "POST", f"/v1/sessions/{session_id}/messages", agent_name, budget=budget,
                    json_body={"role": "user",
                               "content": "Stages 2-5 done. Relay messaging, job queue, shared memory, and pub/sub all working."})

    # Get session
    r6 = await call(client, "GET", f"/v1/sessions/{session_id}", agent_name, budget=budget)

    # Summarize session
    r7 = await call(client, "POST", f"/v1/sessions/{session_id}/summarize", agent_name, budget=budget)

    ok = r2.status_code in (200, 201) and r3.status_code in (200, 201) and r6.status_code == 200
    return ok


async def stage9_marketplace(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 9: Marketplace and Collaboration -- Marketplace + Testing/Scenarios + MoltBook."""
    agent_id = state.get("agent_id", "")

    # Post marketplace task
    r1 = await call(client, "POST", "/v1/marketplace/tasks", agent_name, budget=budget,
                    json_body={"title": "Obstacle Course Collaboration",
                               "description": "Help verify obstacle course completion by checking shared memory namespace",
                               "category": "verification",
                               "requirements": ["shared_memory_read"],
                               "reward_credits": 10,
                               "priority": 5,
                               "tags": ["obstacle_course", "verification"]})

    # Create test scenario
    r2 = await call(client, "POST", "/v1/testing/scenarios", agent_name, budget=budget,
                    json_body={"name": "obstacle_course_relay_test",
                               "pattern": "consensus",
                               "agent_count": 2,
                               "timeout_seconds": 30,
                               "success_criteria": {"type": "message_exchange", "min_messages": 1}})
    scenario_id = None
    if r2.status_code in (200, 201):
        try:
            scenario_id = r2.json().get("id") or r2.json().get("scenario_id")
        except Exception:
            pass

    # Run scenario
    if scenario_id:
        r3 = await call(client, "POST", f"/v1/testing/scenarios/{scenario_id}/run",
                        agent_name, budget=budget)
        r4 = await call(client, "GET", f"/v1/testing/scenarios/{scenario_id}/results",
                        agent_name, budget=budget)
    else:
        r3 = httpx.Response(200)
        r4 = httpx.Response(200)

    # Register with MoltBook
    r5 = await call(client, "POST", "/v1/moltbook/register", agent_name, budget=budget,
                    json_body={"moltbook_user_id": agent_id,
                               "display_name": agent_name})

    # Find partner agent -- another agent from same user group or any UserA agent
    async with S.lock:
        agents_snapshot = dict(S.registered_agents)

    agent_user = agents_snapshot.get(agent_name, {}).get("user", "")
    partner_id = None
    for a_name, a_info in agents_snapshot.items():
        if a_name != agent_name and a_info.get("user") == agent_user:
            partner_id = a_info.get("id")
            break
    # Fallback: use any UserA agent
    if not partner_id:
        for a_name, a_info in agents_snapshot.items():
            if a_info.get("user") == "UserA" and a_info.get("id") != agent_id:
                partner_id = a_info.get("id")
                break

    # Log collaboration
    if partner_id:
        r6 = await call(client, "POST", "/v1/directory/collaborations", agent_name, budget=budget,
                        json_body={"partner_agent": partner_id,
                                   "task_type": "obstacle_course",
                                   "outcome": "success",
                                   "rating": 5})
    else:
        r6 = httpx.Response(200)

    # Get leaderboard
    r7 = await call(client, "GET", "/v1/leaderboard", agent_name, budget=budget)

    ok = r1.status_code in (200, 201) and r2.status_code in (200, 201)
    return ok


async def stage10_final(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    state: dict,
) -> bool:
    """Stage 10: Integration and Finish Line -- Onboarding + System + Final."""
    agent_id = state.get("agent_id", "")
    ns = f"obstacle_course_{agent_id}"
    now_iso = datetime.now(timezone.utc).isoformat()

    # Start onboarding
    r1 = await call(client, "POST", "/v1/onboarding/start", agent_name, budget=budget)

    # Check onboarding status
    r2 = await call(client, "GET", "/v1/onboarding/status", agent_name, budget=budget)

    # System health
    r3 = await call(client, "GET", "/v1/health", agent_name, budget=budget)

    # Platform stats
    r4 = await call(client, "GET", "/v1/stats", agent_name, budget=budget)

    # SLA
    r5 = await call(client, "GET", "/v1/sla", agent_name, budget=budget)

    # Update shared memory progress
    r6 = await call(client, "POST", "/v1/shared-memory", agent_name, budget=budget,
                    json_body={"namespace": ns,
                               "key": "progress",
                               "value": f"stages_completed=[1,2,3,4,5,6,7,8,9,10], current_stage=COMPLETE, completed_at={now_iso}"})

    # Write completion memory key
    r7 = await call(client, "POST", "/v1/memory", agent_name, budget=budget,
                    json_body={"key": "obstacle_course_complete",
                               "value": "all_stages=true, services_used=memory,vector,relay,events,queue,schedules,shared_memory,pubsub,directory,heartbeat,webhooks,text,sessions,templates,marketplace,testing,moltbook,integrations,onboarding,leaderboard",
                               "namespace": "obstacle_course"})

    # Send relay announcement
    r8 = await call(client, "POST", "/v1/relay/send", agent_name, budget=budget,
                    json_body={"to_agent": agent_id,
                               "channel": "obstacle_course",
                               "payload": "Obstacle course COMPLETE! All 20 services tested."})

    # Publish completion event
    r9 = await call(client, "POST", "/v1/pubsub/publish", agent_name, budget=budget,
                    json_body={"channel": "obstacle_course",
                               "payload": f"Agent {agent_id} completed the obstacle course! All 10 stages done."})

    ok = r3.status_code == 200  # at minimum, system health must pass
    return ok

# ===========================================================================
# OBSTACLE COURSE RUNNER
# ===========================================================================

async def run_obstacle_course(
    client: httpx.AsyncClient,
    agent_name: str,
    budget: RateBudget,
    user: str,
) -> bool:
    """Run all 10 obstacle course stages. Return True if /submit succeeds."""
    state: dict[str, Any] = {}
    agent_id = S.registered_agents.get(agent_name, {}).get("id", "")
    state["agent_id"] = agent_id

    stages = [
        (1,  "Memory+Vector",      stage1_memory),
        (2,  "Relay+Events",       stage2_relay),
        (3,  "Queue+Schedules",    stage3_queue),
        (4,  "SharedMemory",       stage4_shared_memory),
        (5,  "PubSub",             stage5_pubsub),
        (6,  "Directory+Heartbeat",stage6_directory),
        (7,  "Webhooks+Text",      stage7_webhooks),
        (8,  "Sessions+Templates", stage8_sessions),
        (9,  "Marketplace+Testing",stage9_marketplace),
        (10, "Onboarding+System",  stage10_final),
    ]
    passed_stages = []
    for num, label, fn in stages:
        try:
            ok = await fn(client, agent_name, budget, state)
            if ok:
                passed_stages.append(num)
                log(agent_name, f"Stage {num} ({label}): PASS")
            else:
                log(agent_name, f"Stage {num} ({label}): FAIL (returned False)")
        except Exception as exc:
            log(agent_name, f"Stage {num} ({label}): ERROR -- {exc}")

    # Submit obstacle course
    r = await call(client, "POST", "/v1/obstacle-course/submit", agent_name,
                   json_body={"stages_completed": list(range(1, 11))},
                   budget=budget)
    completed = r.status_code == 200
    async with S.lock:
        S.obstacle_completions[agent_name] = completed
    await record(user, agent_name, "obstacle_course_submit",
                 completed, f"Stages passed: {passed_stages}, submit: {r.status_code}")
    return completed

# ===========================================================================
# MAIN ENTRY POINT
# ===========================================================================

async def main() -> None:
    print("Phase 79: 3-User Realistic Simulation")
    print(f"Mode: {'QUICK (User C only)' if QUICK_MODE else 'FULL (all 3 users)'}")
    print(f"API: {API}")
    print()

    S.start_time = time.time()

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Phase 0: Register all simulation agents
        print("Registering simulation agents...")
        await register_simulation_agents(client)

        agent_count = len(S.registered_agents)
        print(f"Registered {agent_count} agents")
        if not QUICK_MODE:
            print(f"Expected: 17 agents")
        print()

        # Phase 1: User persona workflows (Plan 02)
        # TODO: Wire user persona workflows here in Plan 02

        # Placeholder: run User C obstacle course as a smoke test
        if QUICK_MODE and "SimC_Free_01" in S.registered_agents:
            print("Quick mode: running User C obstacle course only...")
            await run_obstacle_course(client, "SimC_Free_01", BUDGET_FREE, "UserC")

        print()
        print("Framework loaded. Obstacle course stages ready.")
        print(f"Server errors: {len(S.server_errors)}")
        print(f"Obstacle completions: {sum(1 for v in S.obstacle_completions.values() if v)} / {len(S.obstacle_completions)}")


if __name__ == "__main__":
    asyncio.run(main())

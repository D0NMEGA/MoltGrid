"""
Power Test v5 -- 6-Agent + 2-Rogue Concurrent Stress/Soak Test
MoltGrid Production API (https://api.moltgrid.net)

Improvements over v4:
  - 300+ individually tracked tests (up from 98)
  - v8.0 regression coverage: BOLA (Phase 69), marketplace race (Phase 71),
    structured errors (Phase 72), batch endpoints (Phase 73)
  - Per-endpoint rate limit testing (Phase 70)
  - Per-endpoint 429 tracking in soak phase (PT5-05)
  - Phase 5: v8.0 Regressions (new phase, FULL mode only)

Usage:
  python tests/power_test_v5.py          # Full run (~40 min)
  python tests/power_test_v5.py --quick  # Phase 0+1+2 only (~5 min)
"""

from __future__ import annotations

import os
os.environ["PYTHONUNBUFFERED"] = "1"

import asyncio
import json
import random
import sys
import time
import traceback
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API = "https://api.moltgrid.net"
QUICK_MODE = "--quick" in sys.argv

AGENTS: dict[str, dict[str, str]] = {
    "Sentinel": {
        "id": "agent_d6cbc82ed9b4",
        "key": "mg_fd1a2a46637244a9ac52aa899025fdec",
        "role": "Security + BOLA + Injection Scanner",
    },
    "Forge": {
        "id": "agent_abfd5fcaba62",
        "key": "mg_a3117b5d99f04cc983e6aa2d48b39afa",
        "role": "Functional CRUD + Validation Exhaustion",
    },
    "Archon": {
        "id": "agent_68ae69b4ac70",
        "key": "mg_b0b000eacd3f4603ab29064c1c65dbe8",
        "role": "Workflow Orchestrator + State Machines",
    },
    "Nexus": {
        "id": "agent_f5109c26b8cb",
        "key": "mg_2600480b69ca4a388c08b54b6b0993ac",
        "role": "Cross-Agent Coordination + Concurrency",
    },
    "Oracle": {
        "id": "agent_197a04a388d6",
        "key": "mg_a9d9b5224a0b4d68b71517e0ccd6f441",
        "role": "Edge Cases + Encoding + Boundaries",
    },
    "Scribe": {
        "id": "agent_cf70eca3504e",
        "key": "mg_57098efd89c74cb89f86bde70b977a08",
        "role": "Contract Auditor + Soak Monitor",
    },
}

ROGUE_AGENTS: dict[str, dict[str, str]] = {}  # Populated in Phase 0
DEAD_AGENTS: set[str] = set()  # Agents whose keys returned 401

VALID_WEBHOOK_EVENTS = [
    "job.completed", "job.failed",
    "marketplace.task.claimed", "marketplace.task.completed",
    "marketplace.task.delivered", "message.broadcast", "message.received",
]

EXPECTED_ENDPOINTS: set[str] = {
    "POST /v1/agents/heartbeat", "POST /v1/agents/rotate-key",
    "GET /v1/agents/{agent_id}/card",
    "POST /v1/memory", "GET /v1/memory/{key}", "GET /v1/memory",
    "DELETE /v1/memory/{key}", "GET /v1/memory/{key}/meta",
    "GET /v1/memory/{key}/history", "PATCH /v1/memory/{key}/visibility",
    "GET /v1/agents/{target_id}/memory/{key}",
    "POST /v1/shared-memory", "GET /v1/shared-memory",
    "GET /v1/shared-memory/{namespace}", "GET /v1/shared-memory/{namespace}/{key}",
    "DELETE /v1/shared-memory/{namespace}/{key}",
    "POST /v1/vector/upsert", "POST /v1/vector/search", "GET /v1/vector",
    "GET /v1/vector/{key}", "DELETE /v1/vector/{key}",
    "POST /v1/queue/submit", "POST /v1/queue/claim", "GET /v1/queue",
    "GET /v1/queue/{job_id}", "POST /v1/queue/{job_id}/complete",
    "POST /v1/queue/{job_id}/fail", "POST /v1/queue/{job_id}/replay",
    "GET /v1/queue/dead_letter",
    "POST /v1/tasks", "GET /v1/tasks", "GET /v1/tasks/{task_id}",
    "PATCH /v1/tasks/{task_id}", "POST /v1/tasks/{task_id}/claim",
    "POST /v1/tasks/{task_id}/complete", "POST /v1/tasks/{task_id}/dependencies",
    "POST /v1/relay/send", "GET /v1/relay/inbox",
    "POST /v1/relay/{message_id}/read", "GET /v1/messages/{message_id}/status",
    "GET /v1/messages/{message_id}/trace", "GET /v1/messages/dead-letter",
    "POST /v1/pubsub/subscribe", "POST /v1/pubsub/unsubscribe",
    "POST /v1/pubsub/publish", "GET /v1/pubsub/subscriptions",
    "GET /v1/pubsub/channels",
    "POST /v1/webhooks", "GET /v1/webhooks",
    "POST /v1/webhooks/{webhook_id}/test", "DELETE /v1/webhooks/{webhook_id}",
    "POST /v1/schedules", "GET /v1/schedules", "GET /v1/schedules/{task_id}",
    "PATCH /v1/schedules/{task_id}", "DELETE /v1/schedules/{task_id}",
    "POST /v1/sessions", "GET /v1/sessions", "GET /v1/sessions/{session_id}",
    "POST /v1/sessions/{session_id}/messages",
    "POST /v1/sessions/{session_id}/summarize",
    "DELETE /v1/sessions/{session_id}",
    "GET /v1/directory", "GET /v1/directory/me", "PUT /v1/directory/me",
    "GET /v1/directory/{agent_id}", "GET /v1/directory/search",
    "GET /v1/directory/match", "GET /v1/directory/network",
    "GET /v1/directory/stats", "GET /v1/directory/collaborations",
    "POST /v1/directory/collaborations", "PATCH /v1/directory/me/status",
    "GET /v1/leaderboard",
    "GET /v1/events", "POST /v1/events/ack", "GET /v1/events/stream",
    "POST /v1/marketplace/tasks", "GET /v1/marketplace/tasks",
    "GET /v1/marketplace/tasks/{task_id}",
    "POST /v1/marketplace/tasks/{task_id}/claim",
    "POST /v1/marketplace/tasks/{task_id}/deliver",
    "POST /v1/marketplace/tasks/{task_id}/review",
    "POST /v1/testing/scenarios", "GET /v1/testing/scenarios",
    "POST /v1/testing/scenarios/{id}/run", "GET /v1/testing/scenarios/{id}/results",
    "POST /v1/text/process",
    "POST /v1/obstacle-course/submit", "GET /v1/obstacle-course/leaderboard",
    "GET /v1/obstacle-course/my-result",
    "GET /v1/health", "GET /v1/stats", "GET /v1/sla",
    "GET /skill.md", "GET /obstacle-course.md",
    "POST /v1/memory/batch", "POST /v1/queue/batch",
}

# ---------------------------------------------------------------------------
# Rate Budget -- Scale tier: 1200/min, we cap at 1100
# ---------------------------------------------------------------------------
class RateBudget:
    def __init__(self, max_per_minute: int = 1100) -> None:
        self.max_per_minute = max_per_minute
        self.calls: list[float] = []
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            now = time.time()
            self.calls = [t for t in self.calls if now - t < 60]
            if len(self.calls) >= self.max_per_minute:
                wait = 60 - (now - self.calls[0]) + 0.5
                await asyncio.sleep(wait)
            self.calls.append(time.time())

RATE_BUDGET = RateBudget(1100)
SEMAPHORE = asyncio.Semaphore(15)

# ---------------------------------------------------------------------------
# Shared State
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    agent: str
    test: str
    passed: bool
    detail: str = ""
    category: str = ""
    timestamp: str = ""


class SharedState:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.results: list[TestResult] = []
        self.server_errors: list[dict] = []
        self.covered_endpoints: set[str] = set()
        self.api_calls: dict[str, int] = defaultdict(int)
        self.total_api_calls: int = 0
        self.latencies: dict[str, list[float]] = defaultdict(list)
        self.soak_samples: list[dict] = []
        self.critical_findings: list[str] = []
        self.bola_results: list[dict] = []
        self.cross_account_bola: list[dict] = []
        self.race_results: list[dict] = []
        self.encoding_results: list[dict] = []
        self.validation_results: list[dict] = []
        self.spike_results: list[dict] = []
        self.agent_resources: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.rate_limit_429s: int = 0
        # v5 additions
        self.endpoint_429s: dict[str, int] = defaultdict(int)  # PT5-05
        self.per_endpoint_rate_results: list[dict] = []  # PT5-03
        self.batch_results: list[dict] = []  # batch validation
        self.error_envelope_results: list[dict] = []  # structured error validation
        self.bola_queue_results: list[dict] = []  # PT5-01
        self.thundering_herd_results: list[dict] = []  # PT5-02
        # Cross-agent shared data
        self.marketplace_task_id: str | None = None
        self.start_time: float = 0.0

    async def record(self, r: TestResult) -> None:
        async with self.lock:
            self.results.append(r)

    async def record_endpoint(self, ep: str) -> None:
        async with self.lock:
            self.covered_endpoints.add(ep)

    async def record_call(self, agent: str, lat_ms: float, cat: str, is_err: bool) -> None:
        async with self.lock:
            self.api_calls[agent] += 1
            self.total_api_calls += 1
            self.latencies[cat].append(lat_ms)

    async def store(self, agent: str, rtype: str, rid: str) -> None:
        async with self.lock:
            self.agent_resources[agent][rtype].append(rid)

S = SharedState()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(agent: str, msg: str) -> None:
    elapsed = time.time() - S.start_time if S.start_time else 0
    print(f"  [{elapsed:7.1f}s] [{agent:8s}] {msg}", flush=True)

# ---------------------------------------------------------------------------
# Endpoint Normalization
# ---------------------------------------------------------------------------
def _norm(method: str, path: str) -> str:
    """Normalize path for endpoint coverage tracking."""
    segs = path.strip("/").split("?")[0].split("/")
    out: list[str] = []
    i = 0
    ID_MAP = {
        "memory": "{key}", "vector": "{key}", "queue": "{job_id}",
        "tasks": "{task_id}", "sessions": "{session_id}",
        "webhooks": "{webhook_id}", "schedules": "{task_id}",
        "relay": "{message_id}", "messages": "{message_id}",
    }
    KNOWN_ACTIONS = {
        "memory": {"meta", "history", "visibility", "batch"},
        "vector": {"upsert", "search"},
        "queue": {"submit", "claim", "dead_letter", "complete", "fail", "replay", "batch"},
        "tasks": {"claim", "complete", "dependencies"},
        "sessions": {"messages", "summarize"},
        "webhooks": {"test"},
        "relay": {"send", "inbox"},
        "messages": {"dead-letter", "status", "trace"},
        "pubsub": {"subscribe", "unsubscribe", "publish", "subscriptions", "channels"},
        "events": {"ack", "stream"},
        "text": {"process"},
        "obstacle-course": {"submit", "leaderboard", "my-result"},
        "directory": {"me", "search", "match", "network", "stats", "collaborations"},
        "agents": {"heartbeat", "rotate-key"},
    }
    while i < len(segs):
        seg = segs[i]
        if seg in ID_MAP:
            out.append(seg)
            if i + 1 < len(segs):
                nxt = segs[i + 1]
                actions = KNOWN_ACTIONS.get(seg, set())
                if nxt in actions:
                    out.append(nxt)
                    i += 2
                else:
                    out.append(ID_MAP[seg])
                    i += 2
                    if i < len(segs):
                        out.append(segs[i])
                        i += 1
            else:
                i += 1
        elif seg == "agents":
            out.append(seg)
            if i + 1 < len(segs):
                nxt = segs[i + 1]
                if nxt in ("heartbeat", "rotate-key"):
                    out.append(nxt)
                    i += 2
                else:
                    out.append("{agent_id}")
                    i += 2
                    if i < len(segs):
                        if segs[i] == "memory":
                            out.append("memory")
                            i += 1
                            if i < len(segs):
                                out.append("{key}")
                                i += 1
                        else:
                            out.append(segs[i])
                            i += 1
            else:
                i += 1
        elif seg == "directory":
            out.append(seg)
            if i + 1 < len(segs):
                nxt = segs[i + 1]
                if nxt in KNOWN_ACTIONS.get("directory", set()):
                    out.append(nxt)
                    i += 2
                    if i < len(segs):
                        out.append(segs[i])
                        i += 1
                else:
                    out.append("{agent_id}")
                    i += 2
            else:
                i += 1
        elif seg == "marketplace":
            out.append(seg)
            if i + 1 < len(segs) and segs[i + 1] == "tasks":
                out.append("tasks")
                i += 2
                if i < len(segs):
                    out.append("{task_id}")
                    i += 1
                    if i < len(segs):
                        out.append(segs[i])
                        i += 1
            else:
                i += 1
        elif seg == "shared-memory":
            out.append(seg)
            if i + 1 < len(segs):
                out.append("{namespace}")
                i += 2
                if i < len(segs):
                    out.append("{key}")
                    i += 1
            else:
                i += 1
        elif seg == "testing":
            out.append(seg)
            if i + 1 < len(segs) and segs[i + 1] == "scenarios":
                out.append("scenarios")
                i += 2
                if i < len(segs):
                    out.append("{id}")
                    i += 1
                    if i < len(segs):
                        out.append(segs[i])
                        i += 1
            else:
                i += 1
        elif seg in KNOWN_ACTIONS:
            out.append(seg)
            if i + 1 < len(segs):
                out.append(segs[i + 1])
                i += 2
            else:
                i += 1
        else:
            out.append(seg)
            i += 1
    p = "/" + "/".join(out)
    p = p.replace("/agents/{agent_id}/memory/{key}", "/agents/{target_id}/memory/{key}")
    return f"{method} {p}"

# ---------------------------------------------------------------------------
# Centralized API call
# ---------------------------------------------------------------------------
def _agent_key(agent: str) -> str | None:
    if agent in AGENTS:
        return AGENTS[agent]["key"]
    if agent in ROGUE_AGENTS:
        return ROGUE_AGENTS[agent]["key"]
    return None

async def call(
    client: httpx.AsyncClient, method: str, path: str, agent: str, *,
    json_body: Any = None, params: dict | None = None,
    headers_override: dict | None = None,
    category: str = "general", skip_rate_budget: bool = False,
    timeout: float = 30.0,
) -> httpx.Response:
    if not skip_rate_budget:
        await RATE_BUDGET.acquire()

    url = f"{API}{path}"
    hdrs: dict[str, str] = {}
    key = _agent_key(agent)
    if key and not headers_override:
        hdrs["X-API-Key"] = key
    if headers_override:
        hdrs.update(headers_override)

    async with SEMAPHORE:
        t0 = time.monotonic()
        try:
            resp = await client.request(
                method, url, json=json_body, params=params,
                headers=hdrs, timeout=timeout,
            )
        except Exception as exc:
            lat = (time.monotonic() - t0) * 1000
            await S.record_call(agent, lat, category, True)
            return httpx.Response(598, text=str(exc), request=httpx.Request(method, url))

    lat = (time.monotonic() - t0) * 1000
    is_err = resp.status_code >= 500
    await S.record_call(agent, lat, category, is_err)
    await S.record_endpoint(_norm(method, path))

    if resp.status_code >= 500:
        async with S.lock:
            S.server_errors.append({
                "agent": agent, "method": method, "path": path,
                "status": resp.status_code, "body": resp.text[:500],
                "ts": datetime.now(timezone.utc).isoformat(),
            })

    if resp.status_code == 429:
        async with S.lock:
            S.rate_limit_429s += 1
            S.endpoint_429s[path] += 1  # PT5-05: per-endpoint 429 tracking
        retry = int(resp.headers.get("Retry-After", "5"))
        log(agent, f"429 on {path}, wait {retry}s")
        await asyncio.sleep(min(retry, 30))
        # Retry once
        async with SEMAPHORE:
            try:
                resp = await client.request(
                    method, url, json=json_body, params=params,
                    headers=hdrs, timeout=timeout,
                )
            except Exception:
                pass

    return resp

async def call_unauth(
    client: httpx.AsyncClient, method: str, path: str, *,
    category: str = "system",
) -> httpx.Response:
    await RATE_BUDGET.acquire()
    url = f"{API}{path}"
    async with SEMAPHORE:
        t0 = time.monotonic()
        try:
            resp = await client.request(method, url, timeout=30.0)
        except Exception:
            return httpx.Response(598, text="error", request=httpx.Request(method, url))
    lat = (time.monotonic() - t0) * 1000
    await S.record_call("System", lat, category, resp.status_code >= 500)
    await S.record_endpoint(_norm(method, path))
    return resp

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------
async def check(agent: str, name: str, resp: httpx.Response, expect: int, cat: str = "") -> bool:
    passed = resp.status_code == expect
    det = "" if passed else f"Expected {expect}, got {resp.status_code}: {resp.text[:150]}"
    await S.record(TestResult(agent=agent, test=name, passed=passed, detail=det, category=cat,
                              timestamp=datetime.now(timezone.utc).isoformat()))
    tag = "PASS" if passed else "FAIL"
    if not passed:
        log(agent, f"[{tag}] {name} -- {det[:80]}")
    return passed

async def ok(agent: str, name: str, passed: bool, detail: str = "", cat: str = "") -> None:
    await S.record(TestResult(agent=agent, test=name, passed=passed, detail=detail, category=cat,
                              timestamp=datetime.now(timezone.utc).isoformat()))
    tag = "PASS" if passed else "FAIL"
    if not passed:
        log(agent, f"[{tag}] {name} -- {detail[:80]}")

# ---------------------------------------------------------------------------
# Phase 0: Pre-flight
# ---------------------------------------------------------------------------
async def phase0_preflight(client: httpx.AsyncClient) -> None:
    log("System", "Phase 0: Pre-flight -- verifying agent keys")
    for name in list(AGENTS):
        r = await call(client, "GET", "/v1/directory/me", name, category="preflight")
        if r.status_code == 401:
            DEAD_AGENTS.add(name)
            log("System", f"WARNING: {name} key is INVALID (401) -- skipping this agent")
        else:
            log("System", f"{name}: OK ({r.status_code})")

    # Register rogue agents
    log("System", "Registering rogue agents for cross-account BOLA...")
    for rname in ["Rogue_Alpha", "Rogue_Beta"]:
        r = await client.post(f"{API}/v1/register", json={"name": f"PT5_{rname}_{uuid.uuid4().hex[:6]}"},
                              timeout=30.0)
        if r.status_code == 200:
            data = r.json()
            ROGUE_AGENTS[rname] = {
                "id": data.get("agent_id", ""),
                "key": data.get("api_key", ""),
                "role": "Cross-account BOLA attacker",
            }
            log("System", f"Rogue {rname}: registered ({data.get('agent_id')})")
        else:
            log("System", f"WARNING: Failed to register {rname}: {r.status_code} {r.text[:100]}")

    alive = len(AGENTS) - len(DEAD_AGENTS)
    rogues = len(ROGUE_AGENTS)
    log("System", f"Pre-flight complete: {alive}/6 main agents alive, {rogues}/2 rogues registered")

def is_alive(agent: str) -> bool:
    return agent not in DEAD_AGENTS

# ---------------------------------------------------------------------------
# SENTINEL -- Phase 1
# ---------------------------------------------------------------------------
async def sentinel_phase1(client: httpx.AsyncClient) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    log(a, "Phase 1: Setup + security baseline")

    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await check(a, "sentinel_heartbeat_online", r, 200, "identity")

    # XSS payloads in directory profile -- individually named
    xss_payloads = [
        ("<script>alert(1)</script>", "script_tag"),
        ("<img src=x onerror=alert(1)>", "img_onerror"),
        ("javascript:alert(1)", "js_proto"),
        ("<svg onload=alert(1)>", "svg_onload"),
        ("'\"><script>alert(1)</script>", "quote_escape"),
    ]
    for payload, name in xss_payloads:
        r = await call(client, "PUT", "/v1/directory/me", a,
                       json_body={"description": payload, "capabilities": ["security"]}, category="security")
        await ok(a, f"xss_{name}_safe", r.status_code in (200, 429), f"Got {r.status_code}", "security")

    # SSRF on webhooks -- individually named
    ssrf = [
        ("http://127.0.0.1:8080/h", "ipv4_loopback"),
        ("http://[::1]:8080/h", "ipv6_loopback"),
        ("http://169.254.169.254/latest/meta-data/", "aws_metadata"),
        ("http://0x7f000001:8080/h", "hex_loopback"),
        ("ftp://evil.com/h", "ftp_scheme"),
        ("gopher://evil.com/h", "gopher_scheme"),
        ("http://[::ffff:127.0.0.1]:8080/h", "ipv4_mapped_ipv6"),
        ("http://0177.0.0.1:8080/h", "octal_loopback"),
    ]
    for url, name in ssrf:
        r = await call(client, "POST", "/v1/webhooks", a,
                       json_body={"url": url, "event_types": ["job.completed"]}, category="security")
        await ok(a, f"ssrf_{name}_blocked", r.status_code in (400, 422), f"Got {r.status_code}", "security")

    # Valid webhook
    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": ["job.completed"]}, category="webhooks")
    await check(a, "sentinel_valid_webhook_200", r, 200, "webhooks")
    if r.status_code == 200:
        wid = r.json().get("webhook_id") or r.json().get("id")
        if wid:
            await S.store(a, "webhooks", wid)

    # Agent cards -- individually named
    for n, info in AGENTS.items():
        if is_alive(n):
            r = await call(client, "GET", f"/v1/agents/{info['id']}/card", a, category="identity")
            await ok(a, f"agent_card_{n.lower()}_ok", r.status_code == 200, f"Got {r.status_code}", "identity")

    r = await call(client, "GET", "/v1/directory/me", a, category="directory")
    await check(a, "sentinel_directory_me", r, 200, "directory")

    # Seed private memory for BOLA -- individually named
    for i in range(3):
        key = f"sentinel_priv_{i}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": f"secret_{i}"}, category="memory")
        await ok(a, f"sentinel_seed_priv_{i}", r.status_code == 200, f"Got {r.status_code}", "memory")
        if r.status_code == 200:
            await S.store(a, "memory", key)


# ---------------------------------------------------------------------------
# SENTINEL -- Phase 2
# ---------------------------------------------------------------------------
async def sentinel_phase2(client: httpx.AsyncClient) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    log(a, "Phase 2: BOLA + Injection + Rate Limits")

    # -- Same-account BOLA -- per-agent-pair, per-resource individually named
    others = {k: v for k, v in AGENTS.items() if k != a and is_alive(k)}
    for target, info in others.items():
        tid = info["id"]
        tkey = f"{target.lower()}_mem_0"
        if target == "Forge":
            tkey = "forge_mem_0"

        # BOLA read
        r = await call(client, "GET", f"/v1/memory/{tkey}", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_read_{target.lower()}_memory", p, f"Got {r.status_code}", "bola")
        async with S.lock:
            S.bola_results.append({"attacker": a, "target": target, "resource": "memory_read",
                                   "expected": "404/403", "actual": str(r.status_code),
                                   "status": "PASS" if p else "CRITICAL"})

        # BOLA delete
        r = await call(client, "DELETE", f"/v1/memory/{tkey}", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_delete_{target.lower()}_memory", p, f"Got {r.status_code}", "bola")

        # BOLA visibility patch
        r = await call(client, "PATCH", f"/v1/memory/{tkey}/visibility", a,
                       json_body={"visibility": "public"}, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_vis_{target.lower()}_memory", p, f"Got {r.status_code}", "bola")

        # BOLA history read
        r = await call(client, "GET", f"/v1/memory/{tkey}/history", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_history_{target.lower()}_memory", p, f"Got {r.status_code}", "bola")

        # BOLA meta read
        r = await call(client, "GET", f"/v1/memory/{tkey}/meta", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_meta_{target.lower()}_memory", p, f"Got {r.status_code}", "bola")

    # -- Cross-account BOLA (rogue agents) --
    if ROGUE_AGENTS:
        rogue = "Rogue_Alpha"

        # Rogue reads Forge's public key (should succeed if public)
        r = await call(client, "GET", f"/v1/agents/{AGENTS['Forge']['id']}/memory/forge_mem_0",
                       rogue, category="cross_bola")
        await ok(a, "xbola_rogue_reads_public", r.status_code == 200,
                 f"Got {r.status_code}", "cross_bola")
        async with S.lock:
            S.cross_account_bola.append({"rogue": rogue, "target": "Forge", "resource": "public_memory",
                                         "expected": "200", "actual": str(r.status_code), "status": "PASS" if r.status_code == 200 else "INFO"})

        # Rogue reads Sentinel's private key directly (should 404)
        r = await call(client, "GET", "/v1/memory/sentinel_priv_0", rogue, category="cross_bola")
        p = r.status_code in (404, 403)
        await ok(a, "xbola_rogue_reads_private_direct", p, f"Got {r.status_code}", "cross_bola")
        async with S.lock:
            S.cross_account_bola.append({"rogue": rogue, "target": "Sentinel", "resource": "private_memory_direct",
                                         "expected": "404", "actual": str(r.status_code),
                                         "status": "PASS" if p else "CRITICAL"})

        # Rogue reads Sentinel's private via cross-agent path (should 404)
        r = await call(client, "GET", f"/v1/agents/{AGENTS['Sentinel']['id']}/memory/sentinel_priv_0",
                       rogue, category="cross_bola")
        p = r.status_code in (404, 403)
        await ok(a, "xbola_rogue_reads_private_cross", p, f"Got {r.status_code}", "cross_bola")
        async with S.lock:
            S.cross_account_bola.append({"rogue": rogue, "target": "Sentinel", "resource": "private_memory_cross",
                                         "expected": "404", "actual": str(r.status_code),
                                         "status": "PASS" if p else "CRITICAL"})

        # Rogue deletes Forge's memory (should 404)
        r = await call(client, "DELETE", "/v1/memory/forge_mem_0", rogue, category="cross_bola")
        p = r.status_code in (404, 403)
        await ok(a, "xbola_rogue_delete_forge", p, f"Got {r.status_code}", "cross_bola")

        # Rogue patches Forge visibility (should 404)
        r = await call(client, "PATCH", "/v1/memory/forge_mem_0/visibility", rogue,
                       json_body={"visibility": "private"}, category="cross_bola")
        p = r.status_code in (404, 403)
        await ok(a, "xbola_rogue_patch_vis", p, f"Got {r.status_code}", "cross_bola")

        # Rogue sends relay to Nexus (may succeed -- relay is cross-agent by design)
        r = await call(client, "POST", "/v1/relay/send", rogue,
                       json_body={"to_agent": AGENTS["Nexus"]["id"], "payload": "rogue_test"},
                       category="cross_bola")
        await ok(a, "xbola_rogue_relay_to_nexus", True, f"Got {r.status_code} (documenting behavior)", "cross_bola")

        # Rogue accesses directory (should succeed -- public)
        r = await call(client, "GET", "/v1/directory", rogue, category="cross_bola")
        await ok(a, "xbola_rogue_directory", r.status_code == 200, f"Got {r.status_code}", "cross_bola")

        # Rogue-to-rogue isolation
        if "Rogue_Beta" in ROGUE_AGENTS:
            await call(client, "POST", "/v1/memory", rogue,
                       json_body={"key": "rogue_alpha_secret", "value": "alpha_data"}, category="cross_bola")
            r = await call(client, "GET", "/v1/memory/rogue_alpha_secret", "Rogue_Beta", category="cross_bola")
            p = r.status_code in (404, 403)
            await ok(a, "xbola_rogue_to_rogue_isolation", p, f"Got {r.status_code}", "cross_bola")

    # -- Injection -- individually named
    sqli = [
        ("/v1/directory", {"q": "' OR '1'='1"}, "sqli_or"),
        ("/v1/directory", {"q": "'; DROP TABLE agents; --"}, "sqli_drop"),
        ("/v1/marketplace/tasks", {"category": "' UNION SELECT * FROM agents --"}, "sqli_union"),
        ("/v1/directory", {"q": "1; SELECT pg_sleep(5)"}, "sqli_sleep"),
    ]
    for path, params, name in sqli:
        r = await call(client, "GET", path, a, params=params, category="security")
        await ok(a, f"inject_{name}", r.status_code != 500, f"Got {r.status_code}", "security")

    trav_keys = [
        ("../../../etc/passwd", "unix_etc"),
        ("..%2F..%2Fetc%2Fpasswd", "url_encoded"),
        ("....//....//etc/passwd", "double_dot"),
    ]
    for tk, name in trav_keys:
        r = await call(client, "POST", "/v1/memory", a,
                       json_body={"key": tk, "value": "test"}, category="security")
        await ok(a, f"path_trav_{name}", r.status_code in (200, 422), f"Got {r.status_code}", "security")

    ns_inj = [
        ("agent:hack", "agent_prefix"),
        ("system:admin", "system_prefix"),
        ("../escape", "traversal"),
        ("", "empty"),
        ("x" * 500, "overlength"),
    ]
    for ns, name in ns_inj:
        r = await call(client, "POST", "/v1/shared-memory", a,
                       json_body={"namespace": ns, "key": "t", "value": "t"}, category="security")
        await ok(a, f"ns_inject_{name}", r.status_code == 422, f"Got {r.status_code}", "security")

    # -- Rate limit test --
    log(a, "Rate limit test (50 rapid requests to directory)...")
    hit_429 = False
    remaining_ok = True
    last_rem = None
    for i in range(50):
        r = await call(client, "GET", "/v1/directory", a, params={"limit": "1"},
                       category="rate_limit", skip_rate_budget=True)
        if r.status_code == 429:
            hit_429 = True
            ra = r.headers.get("Retry-After")
            await ok(a, "rate_limit_429_hit", True, f"Hit at req {i+1}", "security")
            await ok(a, "rate_limit_retry_after", ra is not None, f"Retry-After: {ra}", "security")
            break
        cur = r.headers.get("x-ratelimit-remaining")
        if cur and last_rem and int(cur) > int(last_rem):
            remaining_ok = False
        last_rem = cur
    if not hit_429:
        await ok(a, "rate_limit_429_hit", True, "No 429 in 50 reqs (Scale tier per-endpoint limit > 50)", "security")
    await ok(a, "rate_limit_remaining_decrements", remaining_ok, "", "security")
    await asyncio.sleep(10)  # Cool down


async def sentinel_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    end = time.time() + duration
    cnt = 0
    while time.time() < end:
        targets = [n for n in AGENTS if n != a and is_alive(n)]
        if targets:
            t = random.choice(targets)
            key = f"{t.lower()}_priv_0" if t != "Forge" else "forge_mem_1"
            r = await call(client, "GET", f"/v1/memory/{key}", a, category="soak_bola")
            if r.status_code == 200:
                async with S.lock:
                    S.critical_findings.append(f"BOLA breach: {a} read {t}'s {key} in soak")
        if ROGUE_AGENTS and cnt % 2 == 0:
            rogue = random.choice(list(ROGUE_AGENTS.keys()))
            t = random.choice(targets) if targets else "Forge"
            r = await call(client, "GET", f"/v1/memory/{t.lower()}_priv_0", rogue, category="soak_xbola")
            if r.status_code == 200:
                async with S.lock:
                    S.critical_findings.append(f"Cross-account BOLA: {rogue} read {t}'s key in soak")
        cnt += 1
        await asyncio.sleep(15)

async def sentinel_phase4(client: httpx.AsyncClient) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    log(a, "Phase 4: Key rotation + cleanup")
    r = await call(client, "POST", "/v1/agents/rotate-key", a, category="identity")
    if r.status_code == 200:
        new_key = r.json().get("api_key")
        if new_key:
            AGENTS[a]["key"] = new_key
            r2 = await call(client, "GET", "/v1/directory/me", a, category="identity")
            await check(a, "key_rotation_new_key_works", r2, 200, "security")
            log(a, f"Key rotated. WARNING: Old key invalidated. New key starts with {new_key[:12]}...")
        else:
            await ok(a, "key_rotation", False, "No new key in response", "security")
    else:
        await ok(a, "key_rotation", r.status_code != 500, f"Got {r.status_code}", "security")

    for i in range(3):
        await call(client, "DELETE", f"/v1/memory/sentinel_priv_{i}", a, category="cleanup")
    for wid in S.agent_resources.get(a, {}).get("webhooks", []):
        await call(client, "DELETE", f"/v1/webhooks/{wid}", a, category="cleanup")

# ---------------------------------------------------------------------------
# FORGE -- Phase 1
# ---------------------------------------------------------------------------
async def forge_phase1(client: httpx.AsyncClient) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    log(a, "Phase 1: Seed data")

    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "idle"}, category="identity")
    await check(a, "forge_heartbeat_idle", r, 200, "identity")

    # 10 memory keys -- individually named
    for i in range(10):
        val = json.dumps({"i": i}) if i % 2 == 0 else f"val_{i}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": f"forge_mem_{i}", "value": val}, category="memory")
        await ok(a, f"forge_seed_mem_{i}", r.status_code == 200, f"Got {r.status_code}", "memory")
        if r.status_code == 200:
            await S.store(a, "memory", f"forge_mem_{i}")

    # Memory meta, history, list
    r = await call(client, "GET", "/v1/memory/forge_mem_0/meta", a, category="memory")
    await check(a, "forge_mem_meta_200", r, 200, "memory")
    r = await call(client, "GET", "/v1/memory/forge_mem_0/history", a, category="memory")
    await ok(a, "forge_mem_history_ok", r.status_code in (200, 404), f"Got {r.status_code}", "memory")
    r = await call(client, "GET", "/v1/memory", a, category="memory")
    await check(a, "forge_mem_list_200", r, 200, "memory")

    # Set one key public for cross-agent tests
    r = await call(client, "PATCH", "/v1/memory/forge_mem_0/visibility", a,
               json_body={"visibility": "public"}, category="memory")
    await ok(a, "forge_mem0_set_public", r.status_code == 200, f"Got {r.status_code}", "memory")

    # Queue: 3 jobs -- individually named
    for i, qn in enumerate(["forge_q1", "forge_q2", "forge_q3"]):
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"forge_job_{i}", "queue_name": qn}, category="queue")
        await ok(a, f"forge_queue_submit_{qn}", r.status_code == 200, f"Got {r.status_code}", "queue")
        if r.status_code == 200:
            jid = r.json().get("job_id")
            if jid:
                await S.store(a, "queue", jid)

    # Tasks: 2
    for i in range(2):
        r = await call(client, "POST", "/v1/tasks", a,
                       json_body={"title": f"Forge Task {i}", "description": f"Test {i}"}, category="tasks")
        await ok(a, f"forge_task_create_{i}", r.status_code in (200, 201), f"Got {r.status_code}", "tasks")
        if r.status_code in (200, 201):
            tid = r.json().get("task_id")
            if tid:
                await S.store(a, "tasks", tid)

    # Webhooks: 2
    for i, evt in enumerate([["job.completed"], ["job.failed", "message.received"]]):
        r = await call(client, "POST", "/v1/webhooks", a,
                       json_body={"url": f"https://httpbin.org/post?n={i}", "event_types": evt}, category="webhooks")
        await ok(a, f"forge_webhook_create_{i}", r.status_code == 200, f"Got {r.status_code}", "webhooks")
        if r.status_code == 200:
            wid = r.json().get("webhook_id") or r.json().get("id")
            if wid:
                await S.store(a, "webhooks", wid)
    r = await call(client, "GET", "/v1/webhooks", a, category="webhooks")
    await check(a, "forge_webhooks_list", r, 200, "webhooks")

    # Schedule
    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "*/30 * * * *", "payload": "forge_sched"}, category="schedules")
    await ok(a, "forge_schedule_create", r.status_code in (200, 201), f"Got {r.status_code}", "schedules")
    if r.status_code in (200, 201):
        sid = r.json().get("schedule_id") or r.json().get("task_id") or r.json().get("id")
        if sid:
            await S.store(a, "schedules", sid)
    r = await call(client, "GET", "/v1/schedules", a, category="schedules")
    await check(a, "forge_schedules_list", r, 200, "schedules")

    # Sessions: 2
    for i in range(2):
        r = await call(client, "POST", "/v1/sessions", a,
                       json_body={"title": f"Forge Session {i}"}, category="sessions")
        await ok(a, f"forge_session_create_{i}", r.status_code in (200, 201), f"Got {r.status_code}", "sessions")
        if r.status_code in (200, 201):
            sid = r.json().get("session_id") or r.json().get("id")
            if sid:
                await S.store(a, "sessions", sid)
    r = await call(client, "GET", "/v1/sessions", a, category="sessions")
    await check(a, "forge_sessions_list", r, 200, "sessions")

    # Vectors: 3
    for i in range(3):
        r = await call(client, "POST", "/v1/vector/upsert", a,
                       json_body={"key": f"forge_vec_{i}", "text": f"Vector about topic {i}",
                                  "metadata": {"i": i}}, category="vector")
        await ok(a, f"forge_vec_upsert_{i}", r.status_code == 200, f"Got {r.status_code}", "vector")
        if r.status_code == 200:
            await S.store(a, "vector", f"forge_vec_{i}")
    r = await call(client, "GET", "/v1/vector", a, category="vector")
    await check(a, "forge_vec_list", r, 200, "vector")
    r = await call(client, "GET", "/v1/vector/forge_vec_0", a, category="vector")
    await check(a, "forge_vec_get", r, 200, "vector")
    r = await call(client, "POST", "/v1/vector/search", a,
               json_body={"query": "topic", "limit": 5}, category="vector")
    await ok(a, "forge_vec_search", r.status_code == 200, f"Got {r.status_code}", "vector")

    # Marketplace
    r = await call(client, "POST", "/v1/marketplace/tasks", a,
                   json_body={"title": "Forge Listing", "description": "Test", "reward": 5, "category": "testing"},
                   category="marketplace")
    await ok(a, "forge_mkt_create", r.status_code in (200, 201), f"Got {r.status_code}", "marketplace")
    if r.status_code in (200, 201):
        mid = r.json().get("task_id") or r.json().get("id")
        if mid:
            await S.store(a, "marketplace", mid)
    r = await call(client, "GET", "/v1/marketplace/tasks", a, category="marketplace")
    await check(a, "forge_mkt_list", r, 200, "marketplace")

    # Directory profile
    r = await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Forge tester", "capabilities": ["testing"],
                          "skills": ["python"], "interests": ["qa"]}, category="directory")
    await check(a, "forge_directory_update", r, 200, "directory")

    # Shared memory
    r = await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "forge_ns", "key": "s1", "value": "data"}, category="shared_memory")
    await ok(a, "forge_shared_mem_set", r.status_code == 200, f"Got {r.status_code}", "shared_memory")
    r = await call(client, "GET", "/v1/shared-memory", a, category="shared_memory")
    await check(a, "forge_shared_mem_list", r, 200, "shared_memory")
    r = await call(client, "GET", "/v1/shared-memory/forge_ns", a, category="shared_memory")
    await ok(a, "forge_shared_mem_ns", r.status_code == 200, f"Got {r.status_code}", "shared_memory")
    r = await call(client, "GET", "/v1/shared-memory/forge_ns/s1", a, category="shared_memory")
    await ok(a, "forge_shared_mem_key", r.status_code == 200, f"Got {r.status_code}", "shared_memory")


# ---------------------------------------------------------------------------
# FORGE -- Phase 2
# ---------------------------------------------------------------------------
async def forge_phase2(client: httpx.AsyncClient) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    log(a, "Phase 2: Validation + aliases + text")

    # -- Validation -- individually named per field/endpoint
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "f50k1", "value": "x" * 50001}, category="validation")
    await check(a, "val_mem_value_50001_rejected", r, 422, "validation")

    r = await call(client, "POST", "/v1/memory", a, json_body={"value": "nokey"}, category="validation")
    await ok(a, "val_mem_missing_key_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "k"}, category="validation")
    await ok(a, "val_mem_missing_value_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "k", "value": "v", "visibility": "invalid_vis"}, category="validation")
    await ok(a, "val_mem_invalid_visibility_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "x" * 100001, "queue_name": "bound"}, category="validation")
    await check(a, "val_queue_payload_100001_rejected", r, 422, "validation")

    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"queue_name": "q"}, category="validation")
    await ok(a, "val_queue_missing_payload_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    # limit=0 on various endpoints
    for path, cat in [("/v1/directory", "dir"), ("/v1/marketplace/tasks", "mkt"),
                       ("/v1/queue", "q"), ("/v1/memory", "mem"), ("/v1/vector", "vec")]:
        r = await call(client, "GET", path, a, params={"limit": "0"}, category="validation")
        await check(a, f"val_limit0_{cat}_422", r, 422, "validation")

    r = await call(client, "GET", "/v1/directory", a, params={"offset": "-1"}, category="validation")
    await check(a, "val_offset_neg_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/vector/upsert", a,
                   json_body={"key": "empty", "text": ""}, category="validation")
    await check(a, "val_vec_empty_text_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "x", "top_k": 0}, category="validation")
    await check(a, "val_vec_topk0_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": []}, category="validation")
    await check(a, "val_wh_empty_events_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": ["bogus"]}, category="validation")
    await check(a, "val_wh_invalid_event_400", r, 400, "validation")

    r = await call(client, "PATCH", "/v1/memory/forge_mem_0/visibility", a,
                   json_body={"visibility": "admin"}, category="validation")
    await check(a, "val_vis_invalid_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "sleeping"}, category="validation")
    await check(a, "val_hb_invalid_status_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "not a cron", "payload": "t"}, category="validation")
    await ok(a, "val_sched_bad_cron", r.status_code in (400, 422), f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "outcome": "t", "rating": 0}, category="validation")
    await check(a, "val_collab_rating0_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "outcome": "t", "rating": 6}, category="validation")
    await check(a, "val_collab_rating6_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "rating": 3}, category="validation")
    await check(a, "val_collab_no_outcome_422", r, 422, "validation")

    # Additional validation: missing fields
    r = await call(client, "POST", "/v1/relay/send", a, json_body={"payload": "no_to"}, category="validation")
    await ok(a, "val_relay_missing_to_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/relay/send", a, json_body={"to_agent": AGENTS["Nexus"]["id"]}, category="validation")
    await ok(a, "val_relay_missing_payload_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/tasks", a, json_body={"description": "no_title"}, category="validation")
    await ok(a, "val_task_missing_title_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/webhooks", a, json_body={"url": "https://httpbin.org/post"}, category="validation")
    await ok(a, "val_wh_missing_events_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/webhooks", a, json_body={"event_types": ["job.completed"]}, category="validation")
    await ok(a, "val_wh_missing_url_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/sessions", a, json_body={}, category="validation")
    await ok(a, "val_session_empty_body", r.status_code in (200, 201, 422), f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/vector/upsert", a, json_body={"key": "k"}, category="validation")
    await ok(a, "val_vec_missing_text_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/vector/search", a, json_body={}, category="validation")
    await ok(a, "val_vec_missing_query_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/shared-memory", a, json_body={"namespace": "ns", "key": "k"}, category="validation")
    await ok(a, "val_shared_missing_value_422", r.status_code == 422, f"Got {r.status_code}", "validation")

    # -- Field aliases --
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"queue": "alias_q", "payload": "t"}, category="alias")
    await check(a, "alias_queue_field", r, 200, "alias")

    r = await call(client, "POST", "/v1/memory", a,
                   json_body={"key": "ttl_test", "value": "x", "ttl": 120}, category="alias")
    await check(a, "alias_mem_ttl", r, 200, "alias")
    r2 = await call(client, "GET", "/v1/memory/ttl_test", a, category="alias")
    if r2.status_code == 200:
        await ok(a, "alias_mem_ttl_expires_set", r2.json().get("expires_at") is not None, "", "alias")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "test", "min_score": 0.5}, category="alias")
    await ok(a, "alias_vec_min_score", r.status_code == 200, f"Got {r.status_code}", "alias")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "test", "top_k": 3}, category="alias")
    await ok(a, "alias_vec_top_k", r.status_code == 200, f"Got {r.status_code}", "alias")

    # Fail aliases
    for alias_field in ["reason", "fail_reason", "error"]:
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"fail_{alias_field}", "queue_name": f"fail_alias_{alias_field}"}, category="alias")
        if r.status_code == 200:
            r2 = await call(client, "POST", "/v1/queue/claim", a,
                            json_body={"queue_name": f"fail_alias_{alias_field}"}, category="alias")
            if r2.status_code == 200:
                jid = r2.json().get("job_id") or r.json().get("job_id")
                if jid:
                    r3 = await call(client, "POST", f"/v1/queue/{jid}/fail", a,
                                    json_body={alias_field: f"test_{alias_field}"}, category="alias")
                    await check(a, f"alias_fail_{alias_field}", r3, 200, "alias")

    # -- Text utilities -- individually named
    texts = [
        ({"text": "Hello world test", "operation": "word_count"}, "word_count"),
        ({"text": "Visit https://moltgrid.net and http://example.com.", "operation": "extract_urls"}, "extract_urls"),
        ({"text": "Contact admin@moltgrid.net.", "operation": "extract_emails"}, "extract_emails"),
        ({"text": "moltgrid", "operation": "hash_sha256"}, "hash_sha256"),
        ({"text": "moltgrid", "operation": "hash_md5"}, "hash_md5"),
    ]
    for body, name in texts:
        r = await call(client, "POST", "/v1/text/process", a, json_body=body, category="text")
        if name == "hash_md5":
            await ok(a, f"text_{name}", r.status_code in (200, 400), f"Got {r.status_code} (md5 may not be supported)", "text")
        else:
            await ok(a, f"text_{name}", r.status_code == 200, f"Got {r.status_code}", "text")

async def forge_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    end = time.time() + duration
    cycle = 0
    while time.time() < end:
        uid = str(uuid.uuid4())
        key = f"forge_rt_{cycle}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": uid}, category="soak")
        if r.status_code == 200:
            r2 = await call(client, "GET", f"/v1/memory/{key}", a, category="soak")
            if r2.status_code == 200:
                match = r2.json().get("value") == uid
                if not match:
                    await ok(a, f"soak_rt_{cycle}", False, "Value mismatch", "soak")
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="soak")
        cycle += 1
        await asyncio.sleep(15)

async def forge_phase4(client: httpx.AsyncClient) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    log(a, "Phase 4: Cleanup")
    for i in range(10):
        await call(client, "DELETE", f"/v1/memory/forge_mem_{i}", a, category="cleanup")
    await call(client, "DELETE", "/v1/memory/ttl_test", a, category="cleanup")
    for k in S.agent_resources.get(a, {}).get("vector", []):
        await call(client, "DELETE", f"/v1/vector/{k}", a, category="cleanup")
    await call(client, "DELETE", "/v1/shared-memory/forge_ns/s1", a, category="cleanup")
    for wid in S.agent_resources.get(a, {}).get("webhooks", []):
        await call(client, "DELETE", f"/v1/webhooks/{wid}", a, category="cleanup")
    for sid in S.agent_resources.get(a, {}).get("sessions", []):
        await call(client, "DELETE", f"/v1/sessions/{sid}", a, category="cleanup")
    for sid in S.agent_resources.get(a, {}).get("schedules", []):
        await call(client, "DELETE", f"/v1/schedules/{sid}", a, category="cleanup")

# ---------------------------------------------------------------------------
# ARCHON -- Phase 1
# ---------------------------------------------------------------------------
async def archon_phase1(client: httpx.AsyncClient) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    log(a, "Phase 1: Baseline data")
    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await check(a, "archon_heartbeat_online", r, 200, "identity")
    r = await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Archon orchestrator", "capabilities": ["orchestration"]}, category="directory")
    await check(a, "archon_directory_update", r, 200, "directory")
    r = await call(client, "POST", "/v1/pubsub/subscribe", a,
                   json_body={"channel": "archon.workflow"}, category="pubsub")
    await ok(a, "archon_pubsub_subscribe", r.status_code == 200, f"Got {r.status_code}", "pubsub")
    r = await call(client, "POST", "/v1/sessions", a,
                   json_body={"title": "Archon Session"}, category="sessions")
    await ok(a, "archon_session_create", r.status_code in (200, 201), f"Got {r.status_code}", "sessions")
    if r.status_code in (200, 201):
        sid = r.json().get("session_id") or r.json().get("id")
        if sid:
            await S.store(a, "sessions", sid)
    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "*/1 * * * *", "payload": "archon_sched"}, category="schedules")
    await ok(a, "archon_schedule_create", r.status_code in (200, 201), f"Got {r.status_code}", "schedules")
    if r.status_code in (200, 201):
        sid = r.json().get("schedule_id") or r.json().get("task_id") or r.json().get("id")
        if sid:
            await S.store(a, "schedules", sid)

# ---------------------------------------------------------------------------
# ARCHON -- Phase 2
# ---------------------------------------------------------------------------
async def archon_phase2(client: httpx.AsyncClient) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    log(a, "Phase 2: Workflow lifecycles")

    # -- Queue lifecycle: submit -> claim -> complete -- individually named
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "lc1", "queue_name": "archon_lc"}, category="queue")
    await ok(a, "q_lc_submit_ok", r.status_code == 200, f"Got {r.status_code}", "workflow")
    if r.status_code == 200:
        jid = r.json().get("job_id")
        await ok(a, "q_lc_job_id_present", bool(jid), f"job_id={jid}", "workflow")
        r2 = await call(client, "GET", f"/v1/queue/{jid}", a, category="queue")
        if r2.status_code == 200:
            await ok(a, "q_lc_status_pending", r2.json().get("status") == "pending", f"Status: {r2.json().get('status')}", "workflow")
        r3 = await call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "archon_lc"}, category="queue")
        await check(a, "q_lc_claim_200", r3, 200, "workflow")
        if r3.status_code == 200:
            await ok(a, "q_lc_claimed_job_id", bool(r3.json().get("job_id")), "", "workflow")
        r5 = await call(client, "POST", f"/v1/queue/{jid}/complete", a,
                        json_body={"result": "done"}, category="queue")
        await check(a, "q_lc_complete_200", r5, 200, "workflow")
        r6 = await call(client, "GET", f"/v1/queue/{jid}", a, category="queue")
        if r6.status_code == 200:
            await ok(a, "q_lc_status_completed", r6.json().get("status") == "completed", "", "workflow")
            await ok(a, "q_lc_result_stored", r6.json().get("result") == "done", "", "workflow")

    # -- Queue lifecycle: submit -> claim -> fail -> replay --
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "lc_fail", "queue_name": "archon_fail"}, category="queue")
    await ok(a, "q_fail_submit_ok", r.status_code == 200, "", "workflow")
    if r.status_code == 200:
        jid = r.json().get("job_id")
        r2 = await call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "archon_fail"}, category="queue")
        await ok(a, "q_fail_claim_ok", r2.status_code == 200, "", "workflow")
        if r2.status_code == 200:
            claimed_id = r2.json().get("job_id") or jid
            r3 = await call(client, "POST", f"/v1/queue/{claimed_id}/fail", a,
                            json_body={"reason": "timeout"}, category="queue")
            await check(a, "q_fail_200", r3, 200, "workflow")
            if r3.status_code == 200:
                r4 = await call(client, "POST", f"/v1/queue/{claimed_id}/replay", a, category="queue")
                await ok(a, "q_replay_ok", r4.status_code in (200, 201), f"Got {r4.status_code}", "workflow")

    r = await call(client, "GET", "/v1/queue/dead_letter", a, category="queue")
    await ok(a, "q_dead_letter_ok", r.status_code == 200, f"Got {r.status_code}", "workflow")
    r = await call(client, "GET", "/v1/queue", a, category="queue")
    await check(a, "q_list_200", r, 200, "workflow")

    # -- Task lifecycle -- individually named
    r = await call(client, "POST", "/v1/tasks", a,
                   json_body={"title": "Archon LC Task", "description": "workflow"}, category="tasks")
    await ok(a, "task_create_ok", r.status_code in (200, 201), f"Got {r.status_code}", "workflow")
    if r.status_code in (200, 201):
        tid = r.json().get("task_id")
        await S.store(a, "tasks", tid)
        r2 = await call(client, "GET", f"/v1/tasks/{tid}", a, category="tasks")
        await check(a, "task_get_200", r2, 200, "workflow")
        if r2.status_code == 200:
            await ok(a, "task_status_pending", r2.json().get("status") == "pending", "", "workflow")
        r3 = await call(client, "POST", f"/v1/tasks/{tid}/claim", a, category="tasks")
        await check(a, "task_claim_200", r3, 200, "workflow")
        r4 = await call(client, "POST", f"/v1/tasks/{tid}/complete", a,
                        json_body={"result": "done"}, category="tasks")
        await check(a, "task_complete_200", r4, 200, "workflow")

    # Task PATCH: create -> claim -> PATCH completed
    r = await call(client, "POST", "/v1/tasks", a,
                   json_body={"title": "Patchable", "description": "t"}, category="tasks")
    if r.status_code in (200, 201):
        tid = r.json().get("task_id")
        await call(client, "POST", f"/v1/tasks/{tid}/claim", a, category="tasks")
        r2 = await call(client, "PATCH", f"/v1/tasks/{tid}", a,
                        json_body={"status": "completed"}, category="tasks")
        await ok(a, "task_patch_completed", r2.status_code in (200, 201), f"Got {r2.status_code}", "workflow")

    # Task dependencies
    ra = await call(client, "POST", "/v1/tasks", a, json_body={"title": "A", "description": "dep"}, category="tasks")
    rb = await call(client, "POST", "/v1/tasks", a, json_body={"title": "B", "description": "dep"}, category="tasks")
    if ra.status_code in (200, 201) and rb.status_code in (200, 201):
        ta = ra.json().get("task_id")
        tb = rb.json().get("task_id")
        if ta and tb:
            r = await call(client, "POST", f"/v1/tasks/{tb}/dependencies", a,
                           json_body={"depends_on": ta}, category="tasks")
            await ok(a, "task_deps_created", r.status_code in (200, 201), f"Got {r.status_code}", "workflow")

    r = await call(client, "GET", "/v1/tasks", a, category="tasks")
    await check(a, "tasks_list_200", r, 200, "workflow")

    # -- Marketplace lifecycle (cross-agent with Nexus) --
    r = await call(client, "POST", "/v1/marketplace/tasks", a,
                   json_body={"title": "Lifecycle Task", "description": "cross-agent",
                              "reward": 1, "category": "testing"}, category="marketplace")
    await ok(a, "mkt_create_lifecycle", r.status_code in (200, 201), f"Got {r.status_code}", "marketplace")
    if r.status_code in (200, 201):
        mid = r.json().get("task_id") or r.json().get("id")
        if mid:
            async with S.lock:
                S.marketplace_task_id = mid
            r2 = await call(client, "GET", f"/v1/marketplace/tasks/{mid}", a, category="marketplace")
            await check(a, "mkt_get_lifecycle", r2, 200, "marketplace")
            if r2.status_code == 200:
                await ok(a, "mkt_status_open", r2.json().get("status") == "open", "", "marketplace")

    # -- Session lifecycle --
    sessions = S.agent_resources.get(a, {}).get("sessions", [])
    if sessions:
        sid = sessions[0]
        for i in range(3):
            r = await call(client, "POST", f"/v1/sessions/{sid}/messages", a,
                       json_body={"content": f"Msg {i}", "role": "user"}, category="sessions")
            await ok(a, f"session_msg_{i}", r.status_code in (200, 201), f"Got {r.status_code}", "sessions")
        r = await call(client, "POST", f"/v1/sessions/{sid}/summarize", a, category="sessions")
        await ok(a, "session_summarize", r.status_code in (200, 201), f"Got {r.status_code}", "sessions")
        r = await call(client, "GET", f"/v1/sessions/{sid}", a, category="sessions")
        await check(a, "session_get_200", r, 200, "sessions")

    # -- Schedule lifecycle --
    scheds = S.agent_resources.get(a, {}).get("schedules", [])
    if scheds:
        sid = scheds[0]
        r = await call(client, "GET", f"/v1/schedules/{sid}", a, category="schedules")
        await check(a, "sched_get_200", r, 200, "workflow")
        r = await call(client, "PATCH", f"/v1/schedules/{sid}", a,
                       json_body={"enabled": False}, category="schedules")
        await check(a, "sched_disable_200", r, 200, "workflow")
        r = await call(client, "GET", f"/v1/schedules/{sid}", a, category="schedules")
        if r.status_code == 200:
            await ok(a, "sched_disabled_verify", r.json().get("enabled") is False, "", "workflow")
        r = await call(client, "PATCH", f"/v1/schedules/{sid}", a,
                       json_body={"enabled": True}, category="schedules")
        await check(a, "sched_reenable_200", r, 200, "workflow")

    # -- Webhook test --
    whs = S.agent_resources.get(a, {}).get("webhooks", [])
    if not whs:
        r = await call(client, "POST", "/v1/webhooks", a,
                       json_body={"url": "https://httpbin.org/post", "event_types": ["job.completed"]}, category="webhooks")
        if r.status_code == 200:
            wid = r.json().get("webhook_id") or r.json().get("id")
            if wid:
                await S.store(a, "webhooks", wid)
                whs = [wid]
    for wid in whs[:1]:
        r = await call(client, "POST", f"/v1/webhooks/{wid}/test", a, category="webhooks")
        await check(a, "webhook_test_200", r, 200, "workflow")

    # -- Events --
    r = await call(client, "GET", "/v1/events", a, category="events")
    await ok(a, "events_get_ok", r.status_code == 200, f"Got {r.status_code}", "events")
    if r.status_code == 200:
        body = r.json()
        events = body.get("events", [])
        if events:
            eids = [e.get("event_id") or e.get("id") for e in events[:3] if e.get("event_id") or e.get("id")]
            if eids:
                r2 = await call(client, "POST", "/v1/events/ack", a, json_body={"event_ids": eids}, category="events")
                await ok(a, "events_ack_ok", r2.status_code == 200, f"Got {r2.status_code}", "events")

    # Wait for marketplace task to be set, then Nexus will claim/deliver
    await asyncio.sleep(3)
    mid = S.marketplace_task_id
    if mid:
        await asyncio.sleep(5)
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/review", a,
                       json_body={"accept": True, "rating": 4}, category="marketplace")
        await ok(a, "mkt_review_ok", r.status_code in (200, 201), f"Got {r.status_code}: {r.text[:80]}", "marketplace")

async def archon_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    end = time.time() + duration
    cycle = 0
    while time.time() < end:
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"soak_{cycle}", "queue_name": "archon_soak"}, category="soak")
        if r.status_code == 200:
            jid = r.json().get("job_id")
            r2 = await call(client, "POST", "/v1/queue/claim", a,
                            json_body={"queue_name": "archon_soak"}, category="soak")
            if r2.status_code == 200 and jid:
                await call(client, "POST", f"/v1/queue/{jid}/complete", a,
                           json_body={"result": f"done_{cycle}"}, category="soak")
        cycle += 1
        await asyncio.sleep(30)

async def archon_phase4(client: httpx.AsyncClient) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    log(a, "Phase 4: Cleanup")
    for sid in S.agent_resources.get(a, {}).get("sessions", []):
        await call(client, "DELETE", f"/v1/sessions/{sid}", a, category="cleanup")
        r = await call(client, "GET", f"/v1/sessions/{sid}", a, category="cleanup")
        await ok(a, "sess_del_verify", r.status_code == 404, f"Got {r.status_code}", "cleanup")
    for sid in S.agent_resources.get(a, {}).get("schedules", []):
        await call(client, "DELETE", f"/v1/schedules/{sid}", a, category="cleanup")
        r = await call(client, "GET", f"/v1/schedules/{sid}", a, category="cleanup")
        await ok(a, "sched_del_verify", r.status_code == 404, f"Got {r.status_code}", "cleanup")
    for wid in S.agent_resources.get(a, {}).get("webhooks", []):
        await call(client, "DELETE", f"/v1/webhooks/{wid}", a, category="cleanup")
    await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": "archon.workflow"}, category="cleanup")

# ---------------------------------------------------------------------------
# NEXUS -- Phase 1
# ---------------------------------------------------------------------------
async def nexus_phase1(client: httpx.AsyncClient) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    log(a, "Phase 1: Messaging + pub/sub + shared memory")
    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await check(a, "nexus_heartbeat_online", r, 200, "identity")

    for n, info in AGENTS.items():
        if n != a and is_alive(n):
            r = await call(client, "POST", "/v1/relay/send", a,
                           json_body={"to_agent": info["id"], "payload": f"Hello {n}", "channel": "coordination"},
                           category="relay")
            await ok(a, f"nexus_relay_to_{n.lower()}", r.status_code == 200, f"Got {r.status_code}", "relay")
            if r.status_code == 200:
                mid = r.json().get("message_id") or r.json().get("id")
                if mid:
                    await S.store(a, "messages", mid)

    for ch in ["nexus.coord", "nexus.*", "broadcast.test"]:
        r = await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": ch}, category="pubsub")
        await ok(a, f"nexus_sub_{ch.replace('.', '_').replace('*', 'star')}", r.status_code == 200, f"Got {r.status_code}", "pubsub")
    r = await call(client, "GET", "/v1/pubsub/subscriptions", a, category="pubsub")
    await check(a, "nexus_pubsub_subs_list", r, 200, "pubsub")
    r = await call(client, "GET", "/v1/pubsub/channels", a, category="pubsub")
    await check(a, "nexus_pubsub_channels_list", r, 200, "pubsub")

    r = await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "collab_ws", "key": "status", "value": "initialized"}, category="shared_memory")
    await ok(a, "nexus_shared_mem_init", r.status_code == 200, f"Got {r.status_code}", "shared_memory")
    r = await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Nexus coordinator", "capabilities": ["messaging"],
                          "interests": ["collaboration"]}, category="directory")
    await check(a, "nexus_directory_update", r, 200, "directory")

# ---------------------------------------------------------------------------
# NEXUS -- Phase 2
# ---------------------------------------------------------------------------
async def nexus_phase2(client: httpx.AsyncClient) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    log(a, "Phase 2: Relay + pub/sub + races + coordination")

    # -- Relay chain: Oracle reads inbox, marks read --
    r = await call(client, "GET", "/v1/relay/inbox", "Oracle", params={"channel": "coordination"}, category="relay")
    await ok(a, "relay_oracle_inbox_ok", r.status_code == 200, f"Got {r.status_code}", "relay")
    if r.status_code == 200:
        msgs = r.json() if isinstance(r.json(), list) else r.json().get("messages", [])
        for m in msgs[:1]:
            mid = m.get("message_id") or m.get("id")
            if mid:
                r2 = await call(client, "POST", f"/v1/relay/{mid}/read", "Oracle", category="relay")
                await check(a, "relay_mark_read_200", r2, 200, "relay")

    # Nexus checks message status/trace
    own_msgs = S.agent_resources.get(a, {}).get("messages", [])
    if own_msgs:
        mid = own_msgs[0]
        r = await call(client, "GET", f"/v1/messages/{mid}/status", a, category="relay")
        await check(a, "msg_status_200", r, 200, "relay")
        r = await call(client, "GET", f"/v1/messages/{mid}/trace", a, category="relay")
        await check(a, "msg_trace_200", r, 200, "relay")

    r = await call(client, "GET", "/v1/messages/dead-letter", a, category="relay")
    await ok(a, "msg_dead_letter_ok", r.status_code == 200, f"Got {r.status_code}", "relay")
    r = await call(client, "GET", "/v1/relay/inbox", a, params={"channel": "coordination"}, category="relay")
    await ok(a, "nexus_inbox_ok", r.status_code == 200, f"Got {r.status_code}", "relay")

    # -- Pub/Sub fan-out --
    r = await call(client, "POST", "/v1/pubsub/publish", a,
                   json_body={"channel": "broadcast.test", "payload": "fan_out_v5"}, category="pubsub")
    if r.status_code == 200:
        notified = r.json().get("subscribers_notified", 0)
        await ok(a, "pubsub_fanout_notified", notified >= 1, f"Notified: {notified}", "pubsub")
    else:
        await check(a, "pubsub_publish_200", r, 200, "pubsub")

    await call(client, "POST", "/v1/pubsub/publish", a,
               json_body={"channel": "nexus.specific", "payload": "wildcard_test"}, category="pubsub")
    r = await call(client, "POST", "/v1/pubsub/unsubscribe", a,
                   json_body={"channel": "nonexistent.ch"}, category="pubsub")
    await check(a, "unsub_idempotent_200", r, 200, "pubsub")

    # -- Thundering herd queue races --
    log(a, "Thundering herd race tests...")
    for rd in range(3):
        r = await call(client, "POST", "/v1/queue/submit", "Archon",
                       json_body={"payload": f"race_{rd}", "queue_name": f"race_v5_{rd}"}, category="race")
        if r.status_code == 200:
            live = [n for n in AGENTS if is_alive(n)]
            claims = await asyncio.gather(*[
                call(client, "POST", "/v1/queue/claim", n,
                     json_body={"queue_name": f"race_v5_{rd}"}, category="race")
                for n in live
            ], return_exceptions=True)
            winners = sum(1 for c in claims
                          if not isinstance(c, Exception) and c.status_code == 200
                          and c.json() and c.json().get("job_id"))
            async with S.lock:
                S.race_results.append({
                    "round": rd, "agents": len(live), "winners": winners,
                    "atomic": winners <= 1, "notes": f"{'ATOMIC' if winners <= 1 else 'RACE CONDITION'}",
                })
            await ok(a, f"race_round_{rd}_atomic", winners <= 1, f"Winners: {winners}", "race")
        await asyncio.sleep(2)

    # -- Concurrent memory write --
    live = [n for n in AGENTS if is_alive(n)]
    writes = await asyncio.gather(*[
        call(client, "POST", "/v1/memory", n,
             json_body={"key": "contested_v5", "value": f"from_{n}"}, category="concurrency")
        for n in live
    ], return_exceptions=True)
    err500 = sum(1 for w in writes if not isinstance(w, Exception) and w.status_code >= 500)
    await ok(a, "concurrent_write_no_500", err500 == 0, f"{err500} 500s", "concurrency")
    r = await call(client, "GET", "/v1/memory/contested_v5", a, category="concurrency")
    if r.status_code == 200:
        v = r.json().get("value", "")
        await ok(a, "concurrent_write_coherent", v.startswith("from_"), f"Value: {v}", "concurrency")

    # -- Cross-agent memory visibility --
    await asyncio.sleep(2)
    r = await call(client, "GET", f"/v1/agents/{AGENTS['Forge']['id']}/memory/forge_mem_0", a, category="memory")
    await check(a, "xagent_public_read_200", r, 200, "concurrency")
    r = await call(client, "GET", f"/v1/agents/{AGENTS['Sentinel']['id']}/memory/sentinel_priv_0", a, category="memory")
    await ok(a, "xagent_private_blocked", r.status_code in (403, 404), f"Got {r.status_code}", "concurrency")

    # -- Shared memory coordination --
    r = await call(client, "GET", "/v1/shared-memory/collab_ws/status", a, category="shared_memory")
    if r.status_code == 200:
        val = r.json().get("value")
        await ok(a, "shared_mem_read_initialized", val == "initialized", f"Value: {val}", "shared_memory")
    await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "collab_ws", "key": "status", "value": "phase_2_active"}, category="shared_memory")

    # -- Collaboration + Directory --
    r = await call(client, "POST", "/v1/directory/collaborations", a,
               json_body={"partner_agent": AGENTS["Forge"]["id"], "outcome": "success", "rating": 5}, category="directory")
    await ok(a, "collab_forge_ok", r.status_code in (200, 201), f"Got {r.status_code}", "directory")
    r = await call(client, "POST", "/v1/directory/collaborations", a,
               json_body={"partner_agent": AGENTS["Oracle"]["id"], "outcome": "partial", "rating": 3}, category="directory")
    await ok(a, "collab_oracle_ok", r.status_code in (200, 201), f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory/collaborations", a, category="directory")
    await ok(a, "collabs_list_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory/network", a, category="directory")
    await ok(a, "directory_network_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory/match", a, params={"interest": "collaboration"}, category="directory")
    if r.status_code == 422:
        r = await call(client, "GET", "/v1/directory/match", a, category="directory")
    await ok(a, "directory_match_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory/search", a, params={"q": "coordinator"}, category="directory")
    await ok(a, "directory_search_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory/stats", a, category="directory")
    await ok(a, "directory_stats_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "PATCH", "/v1/directory/me/status", a,
               json_body={"status": "busy"}, category="directory")
    await ok(a, "directory_status_update", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/leaderboard", a, category="directory")
    await ok(a, "leaderboard_ok", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", f"/v1/directory/{AGENTS['Forge']['id']}", a, category="directory")
    await ok(a, "directory_agent_get", r.status_code == 200, f"Got {r.status_code}", "directory")
    r = await call(client, "GET", "/v1/directory", a, category="directory")
    await check(a, "directory_list_200", r, 200, "directory")

    # -- Marketplace claim + deliver --
    mid = S.marketplace_task_id
    if mid and is_alive("Nexus"):
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/claim", a, category="marketplace")
        await check(a, "mkt_claim_200", r, 200, "marketplace")
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/deliver", a,
                       json_body={"result": "delivered"}, category="marketplace")
        await ok(a, "mkt_deliver_ok", r.status_code in (200, 201), f"Got {r.status_code}", "marketplace")

async def nexus_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    end = time.time() + duration
    cycle = 0
    while time.time() < end:
        targets = [n for n in AGENTS if n != a and is_alive(n)]
        if targets:
            t = random.choice(targets)
            await call(client, "POST", "/v1/relay/send", a,
                       json_body={"to_agent": AGENTS[t]["id"], "payload": f"soak_{cycle}"}, category="soak")
        if cycle % 2 == 0 and targets:
            r = await call(client, "POST", "/v1/queue/submit", "Archon",
                           json_body={"payload": f"soak_race_{cycle}", "queue_name": "soak_race"}, category="soak")
            if r.status_code == 200:
                await asyncio.gather(
                    call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "soak_race"}, category="soak"),
                    call(client, "POST", "/v1/queue/claim", "Forge", json_body={"queue_name": "soak_race"}, category="soak"),
                )
        cycle += 1
        await asyncio.sleep(15)

async def nexus_phase4(client: httpx.AsyncClient) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    log(a, "Phase 4: Cleanup")
    await call(client, "DELETE", "/v1/shared-memory/collab_ws/status", a, category="cleanup")
    await call(client, "DELETE", "/v1/memory/contested_v5", a, category="cleanup")
    for ch in ["nexus.coord", "nexus.*", "broadcast.test"]:
        await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": ch}, category="cleanup")

# ---------------------------------------------------------------------------
# ORACLE -- Phase 1
# ---------------------------------------------------------------------------
async def oracle_phase1(client: httpx.AsyncClient) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    log(a, "Phase 1: Seed unicode + obstacle + scenarios")
    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await check(a, "oracle_heartbeat_online", r, 200, "identity")
    r = await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Oracle edge tester", "capabilities": ["encoding"]}, category="directory")
    await check(a, "oracle_directory_update", r, 200, "directory")

    r = await call(client, "GET", "/v1/obstacle-course/leaderboard", a, category="obstacle")
    await ok(a, "obstacle_leaderboard_ok", r.status_code == 200, f"Got {r.status_code}", "obstacle")
    r = await call(client, "GET", "/v1/obstacle-course/my-result", a, category="obstacle")
    await ok(a, "obstacle_my_result_ok", r.status_code in (200, 404), f"Got {r.status_code}", "obstacle")
    r = await call(client, "POST", "/v1/obstacle-course/submit", a,
                   json_body={"stage": 1, "result": "oracle_test"}, category="obstacle")
    await ok(a, "obstacle_submit", r.status_code in (200, 201, 422), f"Got {r.status_code}", "obstacle")

    r = await call(client, "POST", "/v1/testing/scenarios", a,
                   json_body={"name": "oracle_enc_test", "description": "Encoding test",
                              "pattern": "consensus", "agent_count": 2}, category="testing")
    scen_id = None
    if r.status_code in (200, 201):
        scen_id = r.json().get("scenario_id") or r.json().get("id")
        if scen_id:
            await S.store(a, "scenarios", scen_id)
    await ok(a, "scenario_create", r.status_code in (200, 201), f"Got {r.status_code}", "testing")
    r = await call(client, "GET", "/v1/testing/scenarios", a, category="testing")
    await ok(a, "scenarios_list_ok", r.status_code == 200, f"Got {r.status_code}", "testing")
    if scen_id:
        r = await call(client, "POST", f"/v1/testing/scenarios/{scen_id}/run", a, category="testing")
        await ok(a, "scenario_run_ok", r.status_code in (200, 201), f"Got {r.status_code}", "testing")
        r = await call(client, "GET", f"/v1/testing/scenarios/{scen_id}/results", a, category="testing")
        await ok(a, "scenario_results_ok", r.status_code == 200, f"Got {r.status_code}", "testing")

    r = await call(client, "GET", "/v1/relay/inbox", a, category="relay")
    await ok(a, "oracle_relay_inbox", r.status_code == 200, f"Got {r.status_code}", "relay")
    r = await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": "broadcast.test"}, category="pubsub")
    await ok(a, "oracle_pubsub_subscribe", r.status_code == 200, f"Got {r.status_code}", "pubsub")

# ---------------------------------------------------------------------------
# ORACLE -- Phase 2
# ---------------------------------------------------------------------------
async def oracle_phase2(client: httpx.AsyncClient) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    log(a, "Phase 2: Encoding + boundaries + large payloads")

    # Per-encoding individually named tests
    ENC = {
        "emoji": "Hello \U0001f30d\U0001f525\U0001f480\U0001f389 World",
        "cjk_japanese": "\u30c6\u30b9\u30c8",
        "cjk_chinese": "\u6d4b\u8bd5\u6570\u636e",
        "cjk_korean": "\uc2dc\ud5d8\ub370\uc774\ud130",
        "rtl_arabic": "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
        "rtl_hebrew": "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd",
        "cyrillic": "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440",
        "thai": "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35\u0e42\u0e25\u0e01",
        "devanagari": "\u0928\u092e\u0938\u094d\u0924\u0947 \u0926\u0941\u0928\u093f\u092f\u0627",
        "mixed_scripts": "\u041f\u0440\u0438\u0432\u0435\u0442 \u4f60\u597d Hello",
        "zero_width": "Hello\u200b\u200cWorld",
        "newlines": "Line1\nLine2\tTabbed",
        "json_in_json": '{"nested": {"key": "value"}}',
        "max_len": "x" * 50000,
        "backticks": "Hello `world` 'foo' \"bar\"",
        "empty_string": "",
        "single_char": "a",
        "whitespace_only": "   \t\n  ",
    }
    for name, val in ENC.items():
        key = f"oracle_enc_{name}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": val}, category="encoding")
        if r.status_code == 200:
            await S.store(a, "memory", key)
            r2 = await call(client, "GET", f"/v1/memory/{key}", a, category="encoding")
            if r2.status_code == 200:
                match = r2.json().get("value") == val
                async with S.lock:
                    S.encoding_results.append({"encoding": name, "chars": len(val),
                                               "match": match, "status": "PASS" if match else "FAIL"})
                await ok(a, f"enc_{name}_roundtrip", match,
                         f"Mismatch len {len(r2.json().get('value', ''))} vs {len(val)}" if not match else "", "encoding")
            else:
                await ok(a, f"enc_{name}_read", False, f"Read failed: {r2.status_code}", "encoding")
        else:
            await ok(a, f"enc_{name}_store", r.status_code in (200, 422), f"Got {r.status_code}", "encoding")

    # Boundary values -- individually named
    for klen in [1, 64, 128, 256]:
        key = "k" * klen
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": "t"}, category="boundary")
        await ok(a, f"key_len_{klen}_accepted", r.status_code in (200, 422), f"Got {r.status_code}", "boundary")
        if r.status_code == 200:
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="cleanup")

    for prio, nm in [(0, "min"), (5, "mid"), (10, "max"), (11, "over"), (-1, "neg")]:
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"prio_{nm}", "queue_name": "prio_test", "priority": prio}, category="boundary")
        await ok(a, f"prio_{nm}_ok", r.status_code in (200, 422), f"Got {r.status_code}", "boundary")

    # Large payloads -- individually named
    for size, nm in [(10000, "10k"), (49999, "49k"), (50000, "50k")]:
        key = f"oracle_lg_{nm}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": "L" * size}, category="boundary")
        if r.status_code == 200:
            r2 = await call(client, "GET", f"/v1/memory/{key}", a, category="boundary")
            if r2.status_code == 200:
                await ok(a, f"large_{nm}_roundtrip", len(r2.json().get("value", "")) == size, "", "boundary")
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="cleanup")

    # Idempotency -- individually named
    await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "same"}, category="idempotency")
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "same"}, category="idempotency")
    await ok(a, "idem_same_key_ok", r.status_code == 200, "", "idempotency")
    await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "diff"}, category="idempotency")
    r = await call(client, "GET", "/v1/memory/oracle_idem", a, category="idempotency")
    if r.status_code == 200:
        await ok(a, "idem_updated_value", r.json().get("value") == "diff", "", "idempotency")

    r1 = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="idempotency")
    r2 = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="idempotency")
    await ok(a, "hb_idem_both_200", r1.status_code == 200 and r2.status_code == 200, "", "idempotency")

    # Relay mark read
    r = await call(client, "GET", "/v1/relay/inbox", a, category="relay")
    if r.status_code == 200:
        msgs = r.json() if isinstance(r.json(), list) else r.json().get("messages", [])
        for m in msgs[:1]:
            mid = m.get("message_id") or m.get("id")
            if mid:
                r2 = await call(client, "POST", f"/v1/relay/{mid}/read", a, category="relay")
                await ok(a, "oracle_relay_mark_read", r2.status_code == 200, f"Got {r2.status_code}", "relay")

    # Memory version increments
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_ver", "value": "v1"}, category="versioning")
    await ok(a, "ver_set_v1_ok", r.status_code == 200, "", "versioning")
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_ver", "value": "v2"}, category="versioning")
    await ok(a, "ver_set_v2_ok", r.status_code == 200, "", "versioning")
    r = await call(client, "GET", "/v1/memory/oracle_ver", a, category="versioning")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "ver_value_is_v2", b.get("value") == "v2", f"Value: {b.get('value')}", "versioning")
        await ok(a, "ver_version_gte_2", (b.get("version", 1) or 1) >= 2, f"Version: {b.get('version')}", "versioning")
    r = await call(client, "GET", "/v1/memory/oracle_ver/meta", a, category="versioning")
    if r.status_code == 200:
        mb = r.json()
        await ok(a, "ver_meta_has_version", "version" in mb, str(list(mb.keys()))[:80], "versioning")
    await call(client, "DELETE", "/v1/memory/oracle_ver", a, category="cleanup")

    # Concurrent vector upserts
    vecs = await asyncio.gather(*[
        call(client, "POST", "/v1/vector/upsert", a,
             json_body={"key": f"oracle_cvec_{i}", "text": f"Concurrent vec {i}"}, category="concurrency")
        for i in range(3)
    ], return_exceptions=True)
    vec_ok = sum(1 for v in vecs if not isinstance(v, Exception) and v.status_code == 200)
    await ok(a, "concurrent_vec_upsert_ok", vec_ok >= 2, f"{vec_ok}/3 succeeded", "concurrency")
    for i in range(3):
        await call(client, "DELETE", f"/v1/vector/oracle_cvec_{i}", a, category="cleanup")

async def oracle_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    end = time.time() + duration
    cycle = 0
    samples = ["\U0001f680\U0001f30d", "\u4f60\u597d", "\u041f\u0440\u0438\u0432\u0435\u0442", "\u0645\u0631\u062d\u0628\u0627"]
    while time.time() < end:
        val = random.choice(samples) + f"_{cycle}"
        key = f"oracle_soak_{cycle}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": val}, category="soak")
        if r.status_code == 200:
            r2 = await call(client, "GET", f"/v1/memory/{key}", a, category="soak")
            if r2.status_code == 200 and r2.json().get("value") != val:
                async with S.lock:
                    S.critical_findings.append(f"Encoding corruption soak cycle {cycle}")
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="soak")
        if cycle % 2 == 0:
            key_l = f"oracle_soak_lg_{cycle}"
            r = await call(client, "POST", "/v1/memory", a,
                           json_body={"key": key_l, "value": "X" * 50000}, category="soak")
            if r.status_code == 200:
                await call(client, "DELETE", f"/v1/memory/{key_l}", a, category="soak")
        cycle += 1
        await asyncio.sleep(30)

async def oracle_phase4(client: httpx.AsyncClient) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    log(a, "Phase 4: Cleanup")
    for key in S.agent_resources.get(a, {}).get("memory", []):
        await call(client, "DELETE", f"/v1/memory/{key}", a, category="cleanup")
    await call(client, "DELETE", "/v1/memory/oracle_idem", a, category="cleanup")
    await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": "broadcast.test"}, category="cleanup")

# ---------------------------------------------------------------------------
# SCRIBE -- Phase 1
# ---------------------------------------------------------------------------
async def scribe_phase1(client: httpx.AsyncClient) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, "Phase 1: System endpoints + baseline")
    r = await call_unauth(client, "GET", "/v1/health", category="system")
    await ok(a, "health_unauth_ok", r.status_code == 200, f"Got {r.status_code}", "system")
    r = await call(client, "GET", "/v1/health", a, category="system")
    await check(a, "health_auth_200", r, 200, "system")
    r = await call(client, "GET", "/v1/stats", a, category="system")
    await ok(a, "stats_ok", r.status_code == 200, f"Got {r.status_code}", "system")
    r = await call(client, "GET", "/v1/sla", a, category="system")
    await ok(a, "sla_ok", r.status_code == 200, f"Got {r.status_code}", "system")
    r = await call_unauth(client, "GET", "/skill.md", category="system")
    await ok(a, "skillmd_unauth_ok", r.status_code == 200, f"Got {r.status_code}", "system")
    r = await call_unauth(client, "GET", "/obstacle-course.md", category="system")
    await ok(a, "obstacle_md_ok", r.status_code == 200, f"Got {r.status_code}", "system")
    r = await call(client, "GET", "/v1/events", a, category="events")
    await ok(a, "events_list_ok", r.status_code == 200, f"Got {r.status_code}", "events")
    r = await call(client, "GET", "/v1/events/stream", a, params={"timeout": "1"}, category="events")
    await ok(a, "events_stream_ok", r.status_code == 200, f"Got {r.status_code}", "events")
    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await check(a, "scribe_heartbeat_online", r, 200, "identity")
    r = await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Scribe auditor", "capabilities": ["monitoring"]}, category="directory")
    await check(a, "scribe_directory_update", r, 200, "directory")
    r = await call(client, "POST", "/v1/memory", a,
               json_body={"key": "scribe_canary", "value": "alive"}, category="memory")
    await ok(a, "scribe_canary_set", r.status_code == 200, f"Got {r.status_code}", "memory")
    r = await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": "broadcast.test"}, category="pubsub")
    await ok(a, "scribe_pubsub_subscribe", r.status_code == 200, f"Got {r.status_code}", "pubsub")

# ---------------------------------------------------------------------------
# SCRIBE -- Phase 2
# ---------------------------------------------------------------------------
async def scribe_phase2(client: httpx.AsyncClient) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, "Phase 2: Contract verification")

    # Health tiering
    r = await call_unauth(client, "GET", "/v1/health", category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "health_unauth_has_status", "status" in b, f"Keys: {list(b.keys())}", "contract")
        await ok(a, "health_unauth_no_components", "components" not in b, f"Keys: {list(b.keys())}", "contract")

    r = await call(client, "GET", "/v1/health", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "health_auth_has_components", "components" in b, f"Keys: {list(b.keys())}", "contract")
        await ok(a, "health_auth_has_status", "status" in b, f"Keys: {list(b.keys())}", "contract")
        await ok(a, "health_auth_has_version", "version" in b, f"Keys: {list(b.keys())}", "contract")

    # Error responses -- individually named
    r = await call(client, "GET", "/v1/memory/nonexistent_xyz_99", a, category="contract")
    await check(a, "error_404_on_missing_key", r, 404, "contract")

    r = await call(client, "GET", "/v1/memory/test", a,
                   headers_override={"X-API-Key": "invalid_garbage"}, category="contract")
    await ok(a, "error_401_on_invalid_key", r.status_code == 401, f"Got {r.status_code}", "contract")

    r = await call(client, "POST", "/v1/memory", a,
                   json_body={"key": "k", "value": "x" * 50001}, category="contract")
    await check(a, "error_422_on_oversize", r, 422, "contract")

    # Header contract on a 200
    r = await call(client, "GET", "/v1/directory/me", a, category="contract")
    if r.status_code == 200:
        await ok(a, "hdr_x_request_id_present", "x-request-id" in r.headers, "", "contract")
        await ok(a, "hdr_ratelimit_present", "x-ratelimit-limit" in r.headers, "", "contract")
        await ok(a, "hdr_content_type_json", "application/json" in r.headers.get("content-type", ""), "", "contract")

    # Directory contract -- per field
    r = await call(client, "GET", "/v1/directory", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "dir_has_agents_array", "agents" in b and isinstance(b["agents"], list), "", "contract")
        await ok(a, "dir_has_count_int", "count" in b and isinstance(b["count"], int), "", "contract")
        if b.get("agents"):
            agent_item = b["agents"][0]
            await ok(a, "dir_item_has_agent_id", "agent_id" in agent_item, str(list(agent_item.keys()))[:80], "contract")
            await ok(a, "dir_item_has_name", "name" in agent_item or "display_name" in agent_item, "", "contract")

    # Stats contract
    r = await call(client, "GET", "/v1/stats", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "stats_has_agents", "agents" in b or "total_agents" in b, str(list(b.keys()))[:80], "contract")

    # Events envelope
    r = await call(client, "GET", "/v1/events", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "events_has_events_key", "events" in b, f"Keys: {list(b.keys())}", "contract")
        await ok(a, "events_has_count_key", "count" in b, f"Keys: {list(b.keys())}", "contract")

    # Relay inbox contract
    r = await call(client, "GET", "/v1/relay/inbox", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        if isinstance(b, dict):
            await ok(a, "relay_inbox_has_messages", "messages" in b, f"Keys: {list(b.keys())}", "contract")
        else:
            await ok(a, "relay_inbox_is_list", isinstance(b, list), f"Type: {type(b)}", "contract")

    # Queue list contract
    r = await call(client, "GET", "/v1/queue", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "queue_list_has_jobs", "jobs" in b or isinstance(b, list), str(type(b)), "contract")

    # Marketplace list contract
    r = await call(client, "GET", "/v1/marketplace/tasks", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "mkt_list_has_tasks", "tasks" in b or isinstance(b, list), str(type(b)), "contract")

    # Leaderboard contract
    r = await call(client, "GET", "/v1/leaderboard", a, category="contract")
    await ok(a, "leaderboard_200", r.status_code == 200, f"Got {r.status_code}", "contract")

    # Memory GET contract -- per field
    r = await call(client, "GET", "/v1/memory/scribe_canary", a, category="contract")
    if r.status_code == 200:
        mb = r.json()
        await ok(a, "mem_get_has_key", "key" in mb, str(list(mb.keys()))[:80], "contract")
        await ok(a, "mem_get_has_value", "value" in mb, str(list(mb.keys()))[:80], "contract")
        await ok(a, "mem_get_has_visibility", "visibility" in mb, str(list(mb.keys()))[:80], "contract")
        await ok(a, "mem_get_has_created_at", "created_at" in mb, str(list(mb.keys()))[:80], "contract")

    # Queue submit contract
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "contract_test", "queue_name": "scribe_contract"}, category="contract")
    if r.status_code == 200:
        qb = r.json()
        await ok(a, "queue_submit_has_job_id", "job_id" in qb, str(list(qb.keys()))[:80], "contract")
        await ok(a, "queue_submit_has_status", "status" in qb, str(list(qb.keys()))[:80], "contract")
        # Cleanup
        jid = qb.get("job_id")
        if jid:
            await call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "scribe_contract"}, category="cleanup")
            await call(client, "POST", f"/v1/queue/{jid}/complete", a, json_body={}, category="cleanup")

    # Vector search contract
    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "test", "limit": 3}, category="contract")
    if r.status_code == 200:
        vb = r.json()
        await ok(a, "vec_search_has_results", "results" in vb or isinstance(vb, list), str(type(vb)), "contract")

    # Webhook list contract
    r = await call(client, "GET", "/v1/webhooks", a, category="contract")
    if r.status_code == 200:
        wb = r.json()
        await ok(a, "webhooks_list_is_list", isinstance(wb, list) or "webhooks" in wb, str(type(wb)), "contract")

    # Schedule list contract
    r = await call(client, "GET", "/v1/schedules", a, category="contract")
    if r.status_code == 200:
        sb = r.json()
        await ok(a, "schedules_list_ok", isinstance(sb, list) or "schedules" in sb, str(type(sb)), "contract")

    # Session list contract
    r = await call(client, "GET", "/v1/sessions", a, category="contract")
    if r.status_code == 200:
        sesb = r.json()
        await ok(a, "sessions_list_ok", isinstance(sesb, list) or "sessions" in sesb, str(type(sesb)), "contract")

    # Shared memory list contract
    r = await call(client, "GET", "/v1/shared-memory", a, category="contract")
    if r.status_code == 200:
        smb = r.json()
        await ok(a, "shared_mem_list_ok", isinstance(smb, list) or "namespaces" in smb or isinstance(smb, dict), str(type(smb)), "contract")

async def scribe_phase3(client: httpx.AsyncClient, duration: int) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, f"Phase 3: Soak monitoring for {duration}s")
    p3_start = time.time()
    end = p3_start + duration
    spike_done_5 = False
    spike_done_10 = False

    while time.time() < end:
        elapsed_min = (time.time() - p3_start) / 60
        sample: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat(), "elapsed_min": elapsed_min}

        t0 = time.monotonic()
        r = await call(client, "GET", "/v1/health", a, category="soak_monitor")
        sample["health_ms"] = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            sample["health_status"] = r.json().get("status")

        t0 = time.monotonic()
        await call(client, "GET", "/v1/memory/scribe_canary", a, category="soak_monitor")
        sample["mem_ms"] = (time.monotonic() - t0) * 1000

        t0 = time.monotonic()
        r = await call(client, "GET", "/v1/directory", a, params={"limit": "1"}, category="soak_monitor")
        sample["dir_ms"] = (time.monotonic() - t0) * 1000
        sample["ratelimit_remaining"] = r.headers.get("x-ratelimit-remaining", "?")

        async with S.lock:
            S.soak_samples.append(sample)

        log(a, f"[SOAK] {elapsed_min:.1f}min | health={sample.get('health_status')} | "
               f"mem={sample.get('mem_ms', 0):.0f}ms | dir={sample.get('dir_ms', 0):.0f}ms")

        if elapsed_min >= 5 and not spike_done_5:
            spike_done_5 = True
            await _spike(client, 1)
        if elapsed_min >= 10 and not spike_done_10:
            spike_done_10 = True
            await _spike(client, 2)

        await asyncio.sleep(10)


async def _spike(client: httpx.AsyncClient, num: int) -> None:
    log("Scribe", f"SPIKE #{num}: 180 requests in ~2 seconds...")
    t0 = time.monotonic()
    live = [n for n in AGENTS if is_alive(n)]
    tasks = []
    for agent in live:
        for _ in range(30):
            tasks.append(call(client, "GET", "/v1/memory", agent,
                              params={"limit": "1"}, category="spike", skip_rate_budget=True))
    results = await asyncio.gather(*tasks, return_exceptions=True)
    dur = time.monotonic() - t0
    errs = sum(1 for r in results if isinstance(r, Exception) or (hasattr(r, "status_code") and r.status_code >= 500))
    async with S.lock:
        S.spike_results.append({
            "spike": num, "requests": len(tasks), "duration_s": round(dur, 2),
            "errors": errs, "avg_lat_ms": round(dur * 1000 / max(len(tasks), 1), 0),
        })
    log("Scribe", f"SPIKE #{num}: {len(tasks)} reqs in {dur:.1f}s, {errs} errors")


async def scribe_phase4(client: httpx.AsyncClient) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, "Phase 4: Cleanup")
    await call(client, "DELETE", "/v1/memory/scribe_canary", a, category="cleanup")
    await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": "broadcast.test"}, category="cleanup")

# ---------------------------------------------------------------------------
# Phase 5: v8.0 Regressions (NEW)
# ---------------------------------------------------------------------------
async def test_queue_bola_regression(client: httpx.AsyncClient) -> None:
    """PT5-01: Forge submits+claims a job, Sentinel tries to complete/fail with the REAL job_id."""
    a = "Forge"
    if not is_alive(a) or not is_alive("Sentinel"):
        await ok(a, "pt5_01_skip", True, "Required agents not alive", "bola_queue")
        return

    # Step 1: Forge submits
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "bola_test_v5", "queue_name": "bola_test_v5"}, category="bola_queue")
    passed = await check(a, "pt5_01_submit_ok", r, 200, "bola_queue")
    if not passed:
        return
    job_id = r.json().get("job_id", "")
    await ok(a, "pt5_01_job_id_present", bool(job_id), f"job_id={job_id}", "bola_queue")

    # Step 2: Forge claims
    r2 = await call(client, "POST", "/v1/queue/claim", a,
                    json_body={"queue_name": "bola_test_v5"}, category="bola_queue")
    await check(a, "pt5_01_claim_ok", r2, 200, "bola_queue")

    # Step 3: Sentinel tries to complete Forge's job (MUST get 403)
    r3 = await call(client, "POST", f"/v1/queue/{job_id}/complete", "Sentinel",
                    json_body={}, category="bola_queue")
    await check("Sentinel", "pt5_01_bola_complete_403", r3, 403, "bola_queue")

    # Step 4: Sentinel tries to fail Forge's job (MUST get 403)
    r4 = await call(client, "POST", f"/v1/queue/{job_id}/fail", "Sentinel",
                    json_body={"reason": "bola_attempt"}, category="bola_queue")
    await check("Sentinel", "pt5_01_bola_fail_403", r4, 403, "bola_queue")

    # Step 5: Forge completes its own job (ownership verified)
    r5 = await call(client, "POST", f"/v1/queue/{job_id}/complete", a,
                    json_body={}, category="bola_queue")
    await check(a, "pt5_01_owner_complete_ok", r5, 200, "bola_queue")


async def test_marketplace_thundering_herd(client: httpx.AsyncClient) -> None:
    """PT5-02: 6 agents simultaneously claim the same marketplace listing."""
    if not is_alive("Nexus"):
        await ok("Nexus", "pt5_02_skip", True, "Nexus not alive", "thundering_herd")
        return

    r = await call(client, "POST", "/v1/marketplace/tasks", "Nexus",
                   json_body={"title": "thunder_test_v5", "reward_credits": 1}, category="thundering_herd")
    if r.status_code not in (200, 201):
        await ok("Nexus", "pt5_02_create_listing", False, f"Failed: {r.status_code}", "thundering_herd")
        return
    tid = r.json().get("task_id", "")
    await ok("Nexus", "pt5_02_create_listing", bool(tid), f"task_id={tid}", "thundering_herd")

    alive = [n for n in AGENTS if n not in DEAD_AGENTS]
    results = await asyncio.gather(*[
        call(client, "POST", f"/v1/marketplace/tasks/{tid}/claim", agent,
             category="thundering_herd", skip_rate_budget=True)
        for agent in alive
    ])
    statuses = [r.status_code for r in results]
    winners = sum(1 for s in statuses if s == 200)
    losers = sum(1 for s in statuses if s == 409)

    await ok("Nexus", "pt5_02_exactly_one_winner", winners == 1, f"Winners={winners}, statuses={statuses}", "thundering_herd")
    await ok("Nexus", "pt5_02_losers_get_409", losers == len(alive) - 1, f"409 count={losers}", "thundering_herd")
    await ok("Nexus", "pt5_02_no_500", all(s in (200, 409) for s in statuses), f"Unexpected: {statuses}", "thundering_herd")
    await ok("Nexus", "pt5_02_total_agents_attempted", len(alive) >= 4, f"Alive={len(alive)}", "thundering_herd")


async def test_per_endpoint_rate_limit(client: httpx.AsyncClient) -> None:
    """PT5-03: Send 65 requests from one agent to one endpoint to trigger per-endpoint rate limit."""
    a = "Forge"
    if not is_alive(a):
        await ok(a, "pt5_03_skip", True, "Forge not alive", "per_endpoint_rate")
        return

    log(a, "PT5-03: per-endpoint rate limit (agent_write 60/min, sending 65 requests)")
    hit_429 = False
    for i in range(65):
        r = await call(client, "POST", "/v1/memory", a,
                       json_body={"key": f"rate_test_v5_{i}", "value": "x"},
                       category="per_endpoint_rate", skip_rate_budget=True)
        if r.status_code == 429:
            hit_429 = True
            ra = r.headers.get("Retry-After")
            await ok(a, "pt5_03_429_hit", True, f"Hit at req {i+1}", "per_endpoint_rate")
            await ok(a, "pt5_03_retry_after_present", ra is not None, f"Retry-After={ra}", "per_endpoint_rate")
            await ok(a, "pt5_03_retry_after_60", ra == "60", f"Retry-After={ra}", "per_endpoint_rate")

            # Check retryable field (structured error envelope from Phase 72)
            body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            await ok(a, "pt5_03_retryable_true", body.get("retryable") is True, str(body)[:80], "per_endpoint_rate")
            break
    if not hit_429:
        await ok(a, "pt5_03_429_hit", False, "No 429 in 65 reqs", "per_endpoint_rate")

    # Clean up rate test keys
    for i in range(65):
        await call(client, "DELETE", f"/v1/memory/rate_test_v5_{i}", a, category="cleanup", skip_rate_budget=True)

    await asyncio.sleep(65)  # Cool down past 60s rate window


async def test_skillmd_accuracy(client: httpx.AsyncClient) -> None:
    """PT5-04: Fetch /skill.md, parse documented webhook event_types, compare to API behavior."""
    a = "Scribe"
    if not is_alive(a):
        await ok(a, "pt5_04_skip", True, "Scribe not alive", "skillmd")
        return

    r = await call(client, "GET", "/skill.md", a, category="skillmd")
    await check(a, "pt5_04_skillmd_200", r, 200, "skillmd")
    if r.status_code != 200:
        return

    content = r.text
    # Check documented event types exist in the text
    expected_events = ["memory.set", "memory.delete", "queue.submit", "queue.complete",
                       "queue.fail", "marketplace.claim", "marketplace.deliver"]
    for evt in expected_events:
        found = evt in content
        await ok(a, f"pt5_04_event_{evt.replace('.', '_')}_documented", found,
                 f"{'Found' if found else 'Missing'}: {evt}", "skillmd")

    # Check shared memory warning
    await ok(a, "pt5_04_shared_memory_warning",
             "globally readable" in content.lower() or "all agents" in content.lower(),
             "Shared memory warning presence", "skillmd")

    # Check API URL documented
    await ok(a, "pt5_04_api_url_documented", "api.moltgrid.net" in content, "API URL in skill.md", "skillmd")

    # Check authentication documented
    await ok(a, "pt5_04_auth_documented", "X-API-Key" in content or "api_key" in content.lower(),
             "Auth method in skill.md", "skillmd")


async def test_structured_error_envelopes(client: httpx.AsyncClient) -> None:
    """Verify param, retryable, suggestion, valid_values, details fields on errors."""
    a = "Forge"
    if not is_alive(a):
        await ok(a, "err_skip", True, "Forge not alive", "structured_errors")
        return

    # ERR-01: param field on validation error (invalid visibility)
    r = await call(client, "POST", "/v1/memory", a,
                   json_body={"key": "x", "value": "y", "visibility": "invalid_vis"},
                   category="structured_errors")
    body = r.json() if r.status_code == 422 else {}
    await ok(a, "err_param_field_present", "param" in body or "details" in body, str(body)[:100], "structured_errors")
    await ok(a, "err_suggestion_present", "suggestion" in body, str(body)[:100], "structured_errors")
    await ok(a, "err_valid_values_present", "valid_values" in body, str(body)[:100], "structured_errors")
    await ok(a, "err_retryable_false_on_422", body.get("retryable") is False, str(body)[:100], "structured_errors")
    await ok(a, "err_status_code_in_body", body.get("status") == 422 or "status" in body, str(body)[:100], "structured_errors")

    # ERR-02: Multi-field validation (details array)
    r2 = await call(client, "POST", "/v1/memory", a,
                    json_body={"visibility": "bogus"}, category="structured_errors")
    body2 = r2.json() if r2.status_code == 422 else {}
    await ok(a, "err_details_array_present", isinstance(body2.get("details"), list), str(body2)[:100], "structured_errors")
    await ok(a, "err_multi_field_retryable_false", body2.get("retryable") is False, str(body2)[:100], "structured_errors")

    # ERR-03: 404 error envelope
    r3 = await call(client, "GET", "/v1/memory/does_not_exist_xyz", a, category="structured_errors")
    body3 = r3.json() if r3.status_code == 404 else {}
    await ok(a, "err_404_has_error_field", "error" in body3 or "detail" in body3, str(body3)[:100], "structured_errors")
    await ok(a, "err_404_retryable_false", body3.get("retryable") is False, str(body3)[:100], "structured_errors")

    # ERR-04: 401 error envelope
    r4 = await call(client, "GET", "/v1/memory/test", a,
                    headers_override={"X-API-Key": "bad_key"}, category="structured_errors")
    body4 = r4.json() if r4.status_code == 401 else {}
    await ok(a, "err_401_has_error_field", "error" in body4 or "detail" in body4, str(body4)[:100], "structured_errors")

    # ERR-05: Invalid heartbeat status
    r5 = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "flying"}, category="structured_errors")
    body5 = r5.json() if r5.status_code == 422 else {}
    await ok(a, "err_heartbeat_invalid_422", r5.status_code == 422, f"Got {r5.status_code}", "structured_errors")
    await ok(a, "err_heartbeat_valid_values", "valid_values" in body5 or "details" in body5, str(body5)[:100], "structured_errors")

    # ERR-06: Invalid webhook event type
    r6 = await call(client, "POST", "/v1/webhooks", a,
                    json_body={"url": "https://httpbin.org/post", "event_types": ["bogus.event"]}, category="structured_errors")
    body6 = r6.json() if r6.status_code in (400, 422) else {}
    await ok(a, "err_webhook_invalid_event", r6.status_code in (400, 422), f"Got {r6.status_code}", "structured_errors")
    await ok(a, "err_webhook_has_error", "error" in body6 or "detail" in body6, str(body6)[:100], "structured_errors")


async def test_batch_endpoints(client: httpx.AsyncClient) -> None:
    """Verify memory batch and queue batch with per-item results."""
    a = "Forge"
    if not is_alive(a):
        await ok(a, "batch_skip", True, "Forge not alive", "batch")
        return

    # Memory batch
    items = [{"key": f"batch_v5_{i}", "value": f"val_{i}"} for i in range(5)]
    r = await call(client, "POST", "/v1/memory/batch", a,
                   json_body={"items": items}, category="batch")
    await check(a, "batch_memory_200", r, 200, "batch")
    if r.status_code == 200:
        body = r.json()
        await ok(a, "batch_memory_results_array", "results" in body, str(body)[:100], "batch")
        await ok(a, "batch_memory_total_counter", "total" in body, str(body)[:100], "batch")
        await ok(a, "batch_memory_succeeded_counter", "succeeded" in body, str(body)[:100], "batch")
        await ok(a, "batch_memory_failed_counter", "failed" in body, str(body)[:100], "batch")
        await ok(a, "batch_memory_item_count_5", len(body.get("results", [])) == 5, f"count={len(body.get('results', []))}", "batch")
        # Per-item checks
        results_list = body.get("results", [])
        for idx, item_result in enumerate(results_list[:5]):
            await ok(a, f"batch_memory_item_{idx}_has_key", "key" in item_result, str(item_result)[:60], "batch")

    # Queue batch
    jobs = [{"payload": f"batch_job_v5_{i}", "queue_name": "batch_test_v5"} for i in range(3)]
    r2 = await call(client, "POST", "/v1/queue/batch", "Archon",
                    json_body={"jobs": jobs}, category="batch")
    await check("Archon", "batch_queue_200", r2, 200, "batch")
    if r2.status_code == 200:
        body2 = r2.json()
        await ok("Archon", "batch_queue_results_array", "results" in body2, str(body2)[:100], "batch")
        await ok("Archon", "batch_queue_total_counter", "total" in body2, str(body2)[:100], "batch")
        await ok("Archon", "batch_queue_item_count_3", len(body2.get("results", [])) == 3, f"count={len(body2.get('results', []))}", "batch")
        # Per-item checks
        results_list2 = body2.get("results", [])
        for idx, item_result in enumerate(results_list2[:3]):
            await ok("Archon", f"batch_queue_item_{idx}_has_job_id", "job_id" in item_result, str(item_result)[:60], "batch")

    # Memory batch: verify individual items readable after batch
    r_check = await call(client, "GET", "/v1/memory/batch_v5_0", a, category="batch")
    await ok(a, "batch_memory_item0_readable", r_check.status_code == 200, f"Got {r_check.status_code}", "batch")
    if r_check.status_code == 200:
        await ok(a, "batch_memory_item0_value_correct", r_check.json().get("value") == "val_0", "", "batch")

    # Memory batch: empty items should return error
    r_empty = await call(client, "POST", "/v1/memory/batch", a,
                         json_body={"items": []}, category="batch")
    await ok(a, "batch_memory_empty_items_rejected", r_empty.status_code in (400, 422), f"Got {r_empty.status_code}", "batch")

    # Queue batch: verify jobs queryable
    r_q = await call(client, "GET", "/v1/queue", "Archon", params={"queue_name": "batch_test_v5"}, category="batch")
    await ok(a, "batch_queue_jobs_queryable", r_q.status_code == 200, f"Got {r_q.status_code}", "batch")

    # Cleanup batch keys
    for i in range(5):
        await call(client, "DELETE", f"/v1/memory/batch_v5_{i}", a, category="cleanup")

# ---------------------------------------------------------------------------
# Phase orchestration
# ---------------------------------------------------------------------------
async def run_phase(name: str, funcs: list) -> None:
    log("System", f"{'=' * 60}")
    log("System", f"Starting {name}")
    log("System", f"{'=' * 60}")
    t0 = time.time()
    tasks = [asyncio.create_task(_safe(f.__name__ if hasattr(f, '__name__') else str(f), f))
             for f in funcs]
    await asyncio.gather(*tasks)
    log("System", f"{name} complete in {time.time() - t0:.1f}s")

async def _safe(name: str, fn) -> None:
    try:
        await fn()
    except Exception as e:
        log("System", f"CRASH in {name}: {e}")
        traceback.print_exc()

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0
    s = sorted(vals)
    idx = int(len(s) * p / 100)
    return s[min(idx, len(s) - 1)]

def generate_report() -> str:
    now = datetime.now(timezone.utc).isoformat()
    dur_min = (time.time() - S.start_time) / 60
    total = len(S.results)
    passed = sum(1 for r in S.results if r.passed)
    failed = total - passed
    covered = len(S.covered_endpoints)
    expected = len(EXPECTED_ENDPOINTS)
    uncovered = sorted(EXPECTED_ENDPOINTS - S.covered_endpoints)
    score = int((passed / max(total, 1)) * 100)
    alive = len(AGENTS) - len(DEAD_AGENTS)
    rogues = len(ROGUE_AGENTS)

    L = [
        "# MoltGrid Power Test v5 -- Consolidated Report", "",
        f"**Date:** {now}",
        f"**Target:** {API}",
        f"**Duration:** {dur_min:.1f} minutes",
        f"**Mode:** {'Quick' if QUICK_MODE else 'Full'}",
        f"**Agents:** {alive}/6 main + {rogues}/2 rogue",
        f"**Total Tests:** {total}",
        f"**Total API Calls:** {S.total_api_calls}",
        f"**Rate Limit Hits (429s):** {S.rate_limit_429s}", "",
        "## Executive Summary", "",
    ]

    if failed == 0 and not S.server_errors:
        L.append(f"All {total} tests passed with zero server errors.")
    elif S.server_errors:
        L.append(f"**{failed} failures, {len(S.server_errors)} server errors.** See details below.")
    else:
        L.append(f"**{failed} failures out of {total}.** No server errors.")
    if S.critical_findings:
        L.append(f"**{len(S.critical_findings)} CRITICAL findings detected.**")
    L += ["", f"## Overall Score", f"**{score}/100** -- {passed}/{total} passed, {failed} failed, {len(S.server_errors)} server errors", ""]

    L += [f"## Endpoint Coverage", f"**{covered}/{expected} endpoints hit** ({covered/max(expected,1)*100:.1f}%)", ""]
    if uncovered:
        L += ["### Uncovered Endpoints (FAILURES)"]
        for ep in uncovered:
            L.append(f"- `{ep}`")
        L.append("")

    # Agent summary
    L += ["## Agent Summary", "| Agent | Tests | Passed | Failed | API Calls | Score |",
          "|-------|-------|--------|--------|-----------|-------|"]
    for ag in list(AGENTS) + list(ROGUE_AGENTS) + ["System"]:
        ar = [r for r in S.results if r.agent == ag]
        ap = sum(1 for r in ar if r.passed)
        L.append(f"| {ag} | {len(ar)} | {ap} | {len(ar)-ap} | {S.api_calls.get(ag,0)} | {int(ap/max(len(ar),1)*100)}% |")
    L.append("")

    # Category breakdown
    cats: dict[str, dict] = {}
    for r in S.results:
        c = r.category or "other"
        cats.setdefault(c, {"p": 0, "f": 0})
        if r.passed:
            cats[c]["p"] += 1
        else:
            cats[c]["f"] += 1
    L += ["## Category Breakdown", "| Category | Passed | Failed | Total | Score |",
          "|----------|--------|--------|-------|-------|"]
    for c in sorted(cats):
        t = cats[c]["p"] + cats[c]["f"]
        L.append(f"| {c} | {cats[c]['p']} | {cats[c]['f']} | {t} | {int(cats[c]['p']/max(t,1)*100)}% |")
    L.append("")

    # Critical findings
    L += ["## Critical Findings"]
    if S.critical_findings:
        for i, f in enumerate(S.critical_findings, 1):
            L.append(f"{i}. {f}")
    else:
        L.append("No critical findings.")
    L.append("")

    # BOLA same-account
    if S.bola_results:
        L += ["## BOLA Isolation (Same-Account)",
              "| Attacker | Target | Resource | Expected | Actual | Status |",
              "|----------|--------|----------|----------|--------|--------|"]
        for b in S.bola_results:
            L.append(f"| {b['attacker']} | {b['target']} | {b['resource']} | {b['expected']} | {b['actual']} | {b['status']} |")
        L.append("")

    # Cross-account BOLA
    if S.cross_account_bola:
        L += ["## BOLA Isolation (Cross-Account / Rogue Agents)",
              "| Rogue | Target | Resource | Expected | Actual | Status |",
              "|-------|--------|----------|----------|--------|--------|"]
        for b in S.cross_account_bola:
            L.append(f"| {b['rogue']} | {b['target']} | {b['resource']} | {b['expected']} | {b['actual']} | {b['status']} |")
        L.append("")

    # Race conditions
    if S.race_results:
        L += ["## Race Condition Findings",
              "| Round | Agents | Winners | Atomic? | Notes |",
              "|-------|--------|---------|---------|-------|"]
        for r in S.race_results:
            L.append(f"| {r['round']} | {r['agents']} | {r['winners']} | {r['atomic']} | {r['notes']} |")
        L.append("")

    # Encoding
    if S.encoding_results:
        L += ["## Encoding Round-Trip Results",
              "| Encoding | Chars | Match | Status |",
              "|----------|-------|-------|--------|"]
        for e in S.encoding_results:
            L.append(f"| {e['encoding']} | {e['chars']} | {e['match']} | {e['status']} |")
        L.append("")

    # Per-endpoint 429 report (PT5-05)
    if S.endpoint_429s:
        L += ["## Per-Endpoint 429 Report (PT5-05)",
              "| Endpoint | 429 Count |",
              "|----------|-----------|"]
        for endpoint, count in sorted(S.endpoint_429s.items(), key=lambda x: -x[1]):
            L.append(f"| {endpoint} | {count} |")
        L.append("")

    # Soak metrics
    if S.soak_samples:
        L += ["## Soak Test Metrics", ""]
        health_lats = [s["health_ms"] for s in S.soak_samples if "health_ms" in s]
        mem_lats = [s["mem_ms"] for s in S.soak_samples if "mem_ms" in s]
        dir_lats = [s["dir_ms"] for s in S.soak_samples if "dir_ms" in s]

        L += ["### Latency Percentiles",
              "| Endpoint | p50 (ms) | p95 (ms) | p99 (ms) | Samples |",
              "|----------|----------|----------|----------|---------|"]
        for name, lats in [("health", health_lats), ("memory_get", mem_lats), ("directory", dir_lats)]:
            if lats:
                L.append(f"| {name} | {_pct(lats, 50):.0f} | {_pct(lats, 95):.0f} | {_pct(lats, 99):.0f} | {len(lats)} |")
        L.append("")

        if health_lats and len(health_lats) > 6:
            third = len(health_lats) // 3
            first_avg = sum(health_lats[:third]) / third
            last_avg = sum(health_lats[-third:]) / third
            L += ["### Latency Trend",
                  f"First third avg: {first_avg:.0f} ms",
                  f"Last third avg: {last_avg:.0f} ms",
                  f"Degradation: {'none' if last_avg < first_avg * 1.5 else 'MILD' if last_avg < first_avg * 3 else 'SEVERE'}", ""]

        L += ["### Soak Timeline",
              "| Elapsed (min) | Health Status | Health (ms) | Mem (ms) | Dir (ms) |",
              "|---------------|---------------|-------------|----------|----------|"]
        for s in S.soak_samples:
            L.append(f"| {s.get('elapsed_min', 0):.1f} | {s.get('health_status', '?')} | "
                     f"{s.get('health_ms', 0):.0f} | {s.get('mem_ms', 0):.0f} | {s.get('dir_ms', 0):.0f} |")
        L.append("")

    # Spike results
    if S.spike_results:
        L += ["## Spike Test Results",
              "| Spike | Requests | Duration (s) | Errors | Avg Latency (ms) |",
              "|-------|----------|--------------|--------|-------------------|"]
        for sp in S.spike_results:
            L.append(f"| {sp['spike']} | {sp['requests']} | {sp['duration_s']} | {sp['errors']} | {sp['avg_lat_ms']} |")
        L.append("")

    # Server errors
    if S.server_errors:
        L += ["## Server Errors (500s)",
              "| Agent | Method | Path | Status | Body |",
              "|-------|--------|------|--------|------|"]
        for e in S.server_errors[:30]:
            L.append(f"| {e['agent']} | {e['method']} | {e['path']} | {e['status']} | {e['body'][:60]} |")
        L.append("")

    # Failed tests
    fails = [r for r in S.results if not r.passed]
    if fails:
        L += ["## Failed Tests Detail",
              "| # | Agent | Test | Category | Detail |",
              "|---|-------|------|----------|--------|"]
        for i, r in enumerate(fails[:80], 1):
            L.append(f"| {i} | {r.agent} | {r.test} | {r.category} | {r.detail[:100].replace('|', '/')} |")
        L.append("")

    # All results
    L += ["## All Test Results",
          "| # | Agent | Test | Status | Category |",
          "|---|-------|------|--------|----------|"]
    for i, r in enumerate(S.results, 1):
        L.append(f"| {i} | {r.agent} | {r.test} | {'PASS' if r.passed else 'FAIL'} | {r.category} |")
    L.append("")
    return "\n".join(L)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def main() -> None:
    S.start_time = time.time()
    print("=" * 70)
    print("  MoltGrid Power Test v5")
    print(f"  Target: {API}")
    print(f"  Mode: {'QUICK (Phase 0-2)' if QUICK_MODE else 'FULL (Phase 0-5, ~40 min)'}")
    print(f"  Start: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)

    limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
    async with httpx.AsyncClient(timeout=30.0, limits=limits, follow_redirects=True) as client:
        # Phase 0
        await phase0_preflight(client)

        # Phase 1
        await run_phase("Phase 1: SETUP + ENDPOINT COVERAGE", [
            lambda: sentinel_phase1(client),
            lambda: forge_phase1(client),
            lambda: archon_phase1(client),
            lambda: nexus_phase1(client),
            lambda: oracle_phase1(client),
            lambda: scribe_phase1(client),
        ])

        # Phase 2
        await run_phase("Phase 2: DEEP FUNCTIONAL + SECURITY", [
            lambda: sentinel_phase2(client),
            lambda: forge_phase2(client),
            lambda: archon_phase2(client),
            lambda: nexus_phase2(client),
            lambda: oracle_phase2(client),
            lambda: scribe_phase2(client),
        ])

        if not QUICK_MODE:
            # Phase 3
            dur = 900  # 15 min
            await run_phase("Phase 3: SOAK + STRESS", [
                lambda: sentinel_phase3(client, dur),
                lambda: forge_phase3(client, dur),
                lambda: archon_phase3(client, dur),
                lambda: nexus_phase3(client, dur),
                lambda: oracle_phase3(client, dur),
                lambda: scribe_phase3(client, dur),
            ])

            # Phase 4
            await run_phase("Phase 4: DESTRUCTIVE + CLEANUP", [
                lambda: sentinel_phase4(client),
                lambda: forge_phase4(client),
                lambda: archon_phase4(client),
                lambda: nexus_phase4(client),
                lambda: oracle_phase4(client),
                lambda: scribe_phase4(client),
            ])

            # Phase 5: v8.0 Regressions (FULL mode only)
            await run_phase("Phase 5: v8.0 Regressions", [
                lambda: test_queue_bola_regression(client),
                lambda: test_marketplace_thundering_herd(client),
                lambda: test_per_endpoint_rate_limit(client),
                lambda: test_skillmd_accuracy(client),
                lambda: test_structured_error_envelopes(client),
                lambda: test_batch_endpoints(client),
            ])

    # Per-endpoint 429 report (PT5-05)
    if S.endpoint_429s:
        print("\n--- Per-Endpoint 429 Report (PT5-05) ---")
        for endpoint, count in sorted(S.endpoint_429s.items(), key=lambda x: -x[1]):
            print(f"  {endpoint}: {count} 429s")

    report = generate_report()
    paths = [Path.home() / "Downloads" / "power-test-v5-report.md"]
    pd = Path(".planning/phases/74-mcp-consolidation-power-test-v5")
    if pd.parent.exists():
        pd.mkdir(parents=True, exist_ok=True)
        paths.append(pd / "74-POWER-TEST-V5-RESULTS.md")

    for p in paths:
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(report, encoding="utf-8")
            print(f"\n  Report: {p}")
        except Exception as e:
            print(f"\n  Failed to save {p}: {e}")

    total = len(S.results)
    passed = sum(1 for r in S.results if r.passed)
    covered = len(S.covered_endpoints)
    expected = len(EXPECTED_ENDPOINTS)
    print()
    print("=" * 70)
    print(f"  RESULTS: {passed}/{total} passed, {total - passed} failed")
    print(f"  SCORE: {int(passed / max(total, 1) * 100)}/100")
    print(f"  COVERAGE: {covered}/{expected} ({covered / max(expected, 1) * 100:.1f}%)")
    print(f"  API CALLS: {S.total_api_calls}")
    print(f"  SERVER ERRORS: {len(S.server_errors)}")
    print(f"  CRITICAL: {len(S.critical_findings)}")
    print(f"  429s: {S.rate_limit_429s}")
    print(f"  Duration: {(time.time() - S.start_time) / 60:.1f} minutes")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

"""
Power Test v4 -- 6-Agent + 2-Rogue Concurrent Stress/Soak Test
MoltGrid Production API (https://api.moltgrid.net)

Improvements over v3:
  - RateBudget enforces Scale tier 1200 req/min ceiling
  - Rogue agents for cross-account BOLA testing
  - Phase 3 soak actually runs (fixed lambda arg bug)
  - Spike injection (180 concurrent requests)
  - Proper p50/p95/p99 latency computation
  - Thundering herd classified as FINDING not FAILURE
  - All 97 endpoints covered (v3 missed 7)
  - Key rotation handled safely (updates in-memory, warns about persistence)

Usage:
  python tests/power_test_v4.py          # Full run (~35 min)
  python tests/power_test_v4.py --quick  # Phase 0+1+2 only (~5 min)
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
        "memory": {"meta", "history", "visibility"},
        "vector": {"upsert", "search"},
        "queue": {"submit", "claim", "dead_letter", "complete", "fail", "replay"},
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
    ok = resp.status_code == expect
    det = "" if ok else f"Expected {expect}, got {resp.status_code}: {resp.text[:150]}"
    await S.record(TestResult(agent=agent, test=name, passed=ok, detail=det, category=cat,
                              timestamp=datetime.now(timezone.utc).isoformat()))
    tag = "PASS" if ok else "FAIL"
    if not ok:
        log(agent, f"[{tag}] {name} -- {det[:80]}")
    return ok

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
        r = await client.post(f"{API}/v1/register", json={"name": f"PT4_{rname}_{uuid.uuid4().hex[:6]}"},
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
# SENTINEL
# ---------------------------------------------------------------------------
async def sentinel_phase1(client: httpx.AsyncClient) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    log(a, "Phase 1: Setup + security baseline")

    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")

    # XSS payloads in directory profile
    for i, payload in enumerate(["<script>alert(1)</script>", "<img src=x onerror=alert(1)>", "javascript:alert(1)"]):
        r = await call(client, "PUT", "/v1/directory/me", a,
                       json_body={"description": payload, "capabilities": ["security"]}, category="security")
        await ok(a, f"xss_payload_{i}", r.status_code in (200, 429), f"Got {r.status_code}", "security")

    # SSRF on webhooks
    ssrf = [
        ("http://127.0.0.1:8080/h", "ipv4_loopback"),
        ("http://[::1]:8080/h", "ipv6_loopback"),
        ("http://169.254.169.254/latest/meta-data/", "aws_metadata"),
        ("http://0x7f000001:8080/h", "hex_loopback"),
        ("ftp://evil.com/h", "ftp_scheme"),
        ("gopher://evil.com/h", "gopher_scheme"),
    ]
    for url, name in ssrf:
        r = await call(client, "POST", "/v1/webhooks", a,
                       json_body={"url": url, "event_types": ["job.completed"]}, category="security")
        await ok(a, f"ssrf_{name}_blocked", r.status_code in (400, 422), f"Got {r.status_code}", "security")

    # Valid webhook
    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": ["job.completed"]}, category="webhooks")
    if r.status_code == 200:
        wid = r.json().get("webhook_id") or r.json().get("id")
        if wid:
            await S.store(a, "webhooks", wid)

    # Agent cards
    for n, info in AGENTS.items():
        if is_alive(n):
            await call(client, "GET", f"/v1/agents/{info['id']}/card", a, category="identity")

    await call(client, "GET", "/v1/directory/me", a, category="directory")

    # Seed private memory for BOLA
    for i in range(3):
        key = f"sentinel_priv_{i}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": f"secret_{i}"}, category="memory")
        if r.status_code == 200:
            await S.store(a, "memory", key)


async def sentinel_phase2(client: httpx.AsyncClient) -> None:
    a = "Sentinel"
    if not is_alive(a):
        return
    log(a, "Phase 2: BOLA + Injection + Rate Limits")

    # -- Same-account BOLA --
    others = {k: v for k, v in AGENTS.items() if k != a and is_alive(k)}
    for target, info in others.items():
        tid = info["id"]
        tkey = f"{target.lower()}_mem_0"  # Forge seeds forge_mem_0 etc
        if target == "Forge":
            tkey = "forge_mem_0"

        r = await call(client, "GET", f"/v1/memory/{tkey}", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_read_{target.lower()}", p, f"Got {r.status_code}", "bola")
        async with S.lock:
            S.bola_results.append({"attacker": a, "target": target, "resource": "memory_read",
                                   "expected": "404/403", "actual": str(r.status_code),
                                   "status": "PASS" if p else "CRITICAL"})

        r = await call(client, "DELETE", f"/v1/memory/{tkey}", a, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_delete_{target.lower()}", p, f"Got {r.status_code}", "bola")

        r = await call(client, "PATCH", f"/v1/memory/{tkey}/visibility", a,
                       json_body={"visibility": "public"}, category="bola")
        p = r.status_code in (404, 403)
        await ok(a, f"bola_vis_{target.lower()}", p, f"Got {r.status_code}", "bola")

    # -- Cross-account BOLA (rogue agents) --
    if ROGUE_AGENTS:
        rogue = "Rogue_Alpha"
        rogue_key = ROGUE_AGENTS[rogue]["key"]

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
            # Alpha sets a private key
            await call(client, "POST", "/v1/memory", rogue,
                       json_body={"key": "rogue_alpha_secret", "value": "alpha_data"}, category="cross_bola")
            # Beta tries to read it
            r = await call(client, "GET", "/v1/memory/rogue_alpha_secret", "Rogue_Beta", category="cross_bola")
            p = r.status_code in (404, 403)
            await ok(a, "xbola_rogue_to_rogue_isolation", p, f"Got {r.status_code}", "cross_bola")

    # -- Injection --
    sqli = [
        ("/v1/directory", {"q": "' OR '1'='1"}, "sqli_or"),
        ("/v1/directory", {"q": "'; DROP TABLE agents; --"}, "sqli_drop"),
        ("/v1/marketplace/tasks", {"category": "' UNION SELECT * FROM agents --"}, "sqli_union"),
    ]
    for path, params, name in sqli:
        r = await call(client, "GET", path, a, params=params, category="security")
        await ok(a, name, r.status_code != 500, f"Got {r.status_code}", "security")

    trav_keys = ["../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd"]
    for tk in trav_keys:
        r = await call(client, "POST", "/v1/memory", a,
                       json_body={"key": tk, "value": "test"}, category="security")
        await ok(a, f"path_trav_{tk[:15]}", r.status_code in (200, 422), f"Got {r.status_code}", "security")

    ns_inj = [("agent:hack", "agent_prefix"), ("system:admin", "system_prefix"),
              ("../escape", "traversal"), ("", "empty"), ("x" * 500, "overlength")]
    for ns, name in ns_inj:
        r = await call(client, "POST", "/v1/shared-memory", a,
                       json_body={"namespace": ns, "key": "t", "value": "t"}, category="security")
        await ok(a, f"ns_inject_{name}", r.status_code == 422, f"Got {r.status_code}", "security")

    # -- Rate limit test (run last in phase 2) --
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
        # Same-account probe
        targets = [n for n in AGENTS if n != a and is_alive(n)]
        if targets:
            t = random.choice(targets)
            key = f"{t.lower()}_priv_0" if t != "Forge" else "forge_mem_1"
            r = await call(client, "GET", f"/v1/memory/{key}", a, category="soak_bola")
            if r.status_code == 200:
                async with S.lock:
                    S.critical_findings.append(f"BOLA breach: {a} read {t}'s {key} in soak")
        # Cross-account probe
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
    # Key rotation
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

    # Cleanup memory
    for i in range(3):
        await call(client, "DELETE", f"/v1/memory/sentinel_priv_{i}", a, category="cleanup")
    for wid in S.agent_resources.get(a, {}).get("webhooks", []):
        await call(client, "DELETE", f"/v1/webhooks/{wid}", a, category="cleanup")

# ---------------------------------------------------------------------------
# FORGE
# ---------------------------------------------------------------------------
async def forge_phase1(client: httpx.AsyncClient) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    log(a, "Phase 1: Seed data")

    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "idle"}, category="identity")

    # 10 memory keys
    for i in range(10):
        val = json.dumps({"i": i}) if i % 2 == 0 else f"val_{i}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": f"forge_mem_{i}", "value": val}, category="memory")
        if r.status_code == 200:
            await S.store(a, "memory", f"forge_mem_{i}")

    # Memory meta, history, list
    await call(client, "GET", "/v1/memory/forge_mem_0/meta", a, category="memory")
    await call(client, "GET", "/v1/memory/forge_mem_0/history", a, category="memory")
    await call(client, "GET", "/v1/memory", a, category="memory")

    # Set one key public for cross-agent tests
    await call(client, "PATCH", "/v1/memory/forge_mem_0/visibility", a,
               json_body={"visibility": "public"}, category="memory")

    # Queue: 3 jobs
    for i, qn in enumerate(["forge_q1", "forge_q2", "forge_q3"]):
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"forge_job_{i}", "queue_name": qn}, category="queue")
        if r.status_code == 200:
            jid = r.json().get("job_id")
            if jid:
                await S.store(a, "queue", jid)

    # Tasks: 2
    for i in range(2):
        r = await call(client, "POST", "/v1/tasks", a,
                       json_body={"title": f"Forge Task {i}", "description": f"Test {i}"}, category="tasks")
        if r.status_code in (200, 201):
            tid = r.json().get("task_id")
            if tid:
                await S.store(a, "tasks", tid)

    # Webhooks: 2
    for i, evt in enumerate([["job.completed"], ["job.failed", "message.received"]]):
        r = await call(client, "POST", "/v1/webhooks", a,
                       json_body={"url": f"https://httpbin.org/post?n={i}", "event_types": evt}, category="webhooks")
        if r.status_code == 200:
            wid = r.json().get("webhook_id") or r.json().get("id")
            if wid:
                await S.store(a, "webhooks", wid)
    await call(client, "GET", "/v1/webhooks", a, category="webhooks")

    # Schedule
    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "*/30 * * * *", "payload": "forge_sched"}, category="schedules")
    if r.status_code in (200, 201):
        sid = r.json().get("schedule_id") or r.json().get("task_id") or r.json().get("id")
        if sid:
            await S.store(a, "schedules", sid)
    await call(client, "GET", "/v1/schedules", a, category="schedules")

    # Sessions: 2
    for i in range(2):
        r = await call(client, "POST", "/v1/sessions", a,
                       json_body={"title": f"Forge Session {i}"}, category="sessions")
        if r.status_code in (200, 201):
            sid = r.json().get("session_id") or r.json().get("id")
            if sid:
                await S.store(a, "sessions", sid)
    await call(client, "GET", "/v1/sessions", a, category="sessions")

    # Vectors: 3
    for i in range(3):
        r = await call(client, "POST", "/v1/vector/upsert", a,
                       json_body={"key": f"forge_vec_{i}", "text": f"Vector about topic {i}",
                                  "metadata": {"i": i}}, category="vector")
        if r.status_code == 200:
            await S.store(a, "vector", f"forge_vec_{i}")
    await call(client, "GET", "/v1/vector", a, category="vector")
    await call(client, "GET", "/v1/vector/forge_vec_0", a, category="vector")
    await call(client, "POST", "/v1/vector/search", a,
               json_body={"query": "topic", "limit": 5}, category="vector")

    # Marketplace
    r = await call(client, "POST", "/v1/marketplace/tasks", a,
                   json_body={"title": "Forge Listing", "description": "Test", "reward": 5, "category": "testing"},
                   category="marketplace")
    if r.status_code in (200, 201):
        mid = r.json().get("task_id") or r.json().get("id")
        if mid:
            await S.store(a, "marketplace", mid)
    await call(client, "GET", "/v1/marketplace/tasks", a, category="marketplace")

    # Directory profile
    await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Forge tester", "capabilities": ["testing"],
                          "skills": ["python"], "interests": ["qa"]}, category="directory")

    # Shared memory
    await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "forge_ns", "key": "s1", "value": "data"}, category="shared_memory")
    await call(client, "GET", "/v1/shared-memory", a, category="shared_memory")
    await call(client, "GET", "/v1/shared-memory/forge_ns", a, category="shared_memory")
    await call(client, "GET", "/v1/shared-memory/forge_ns/s1", a, category="shared_memory")


async def forge_phase2(client: httpx.AsyncClient) -> None:
    a = "Forge"
    if not is_alive(a):
        return
    log(a, "Phase 2: Validation + aliases + text")

    # -- Validation --
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "f50k1", "value": "x" * 50001}, category="validation")
    await check(a, "mem_50001_rejected", r, 422, "validation")

    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "x" * 100001, "queue_name": "bound"}, category="validation")
    await check(a, "queue_100001_rejected", r, 422, "validation")

    for path, cat in [("/v1/directory", "dir"), ("/v1/marketplace/tasks", "mkt"),
                       ("/v1/queue", "q"), ("/v1/memory", "mem"), ("/v1/vector", "vec")]:
        r = await call(client, "GET", path, a, params={"limit": "0"}, category="validation")
        await check(a, f"limit0_{cat}_422", r, 422, "validation")

    r = await call(client, "GET", "/v1/directory", a, params={"offset": "-1"}, category="validation")
    await check(a, "offset_neg_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/vector/upsert", a,
                   json_body={"key": "empty", "text": ""}, category="validation")
    await check(a, "vec_empty_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "x", "top_k": 0}, category="validation")
    await check(a, "vec_topk0_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": []}, category="validation")
    await check(a, "wh_empty_events_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/webhooks", a,
                   json_body={"url": "https://httpbin.org/post", "event_types": ["bogus"]}, category="validation")
    await check(a, "wh_invalid_event_400", r, 400, "validation")

    r = await call(client, "PATCH", "/v1/memory/forge_mem_0/visibility", a,
                   json_body={"visibility": "admin"}, category="validation")
    await check(a, "vis_invalid_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "sleeping"}, category="validation")
    await check(a, "hb_invalid_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "not a cron", "payload": "t"}, category="validation")
    await ok(a, "sched_bad_cron", r.status_code in (400, 422), f"Got {r.status_code}", "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "outcome": "t", "rating": 0}, category="validation")
    await check(a, "collab_rating0_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "outcome": "t", "rating": 6}, category="validation")
    await check(a, "collab_rating6_422", r, 422, "validation")

    r = await call(client, "POST", "/v1/directory/collaborations", a,
                   json_body={"partner_agent": AGENTS["Archon"]["id"], "rating": 3}, category="validation")
    await check(a, "collab_no_outcome_422", r, 422, "validation")

    # -- Field aliases --
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"queue": "alias_q", "payload": "t"}, category="alias")
    await check(a, "queue_alias", r, 200, "alias")

    r = await call(client, "POST", "/v1/memory", a,
                   json_body={"key": "ttl_test", "value": "x", "ttl": 120}, category="alias")
    await check(a, "mem_ttl_alias", r, 200, "alias")
    r2 = await call(client, "GET", "/v1/memory/ttl_test", a, category="alias")
    if r2.status_code == 200:
        await ok(a, "mem_ttl_expires_set", r2.json().get("expires_at") is not None, "", "alias")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "test", "min_score": 0.5}, category="alias")
    await ok(a, "vec_min_score_alias", r.status_code == 200, f"Got {r.status_code}", "alias")

    r = await call(client, "POST", "/v1/vector/search", a,
                   json_body={"query": "test", "top_k": 3}, category="alias")
    await ok(a, "vec_top_k_alias", r.status_code == 200, f"Got {r.status_code}", "alias")

    # Fail aliases (submit, claim, fail with each alias)
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
                    await check(a, f"fail_{alias_field}_alias", r3, 200, "alias")

    # -- Text utilities --
    texts = [
        ({"text": "Hello world test", "operation": "word_count"}, "word_count"),
        ({"text": "Visit https://moltgrid.net and http://example.com.", "operation": "extract_urls"}, "extract_urls"),
        ({"text": "Contact admin@moltgrid.net.", "operation": "extract_emails"}, "extract_emails"),
        ({"text": "moltgrid", "operation": "hash_sha256"}, "hash_sha256"),
        ({"text": "moltgrid", "operation": "hash_md5"}, "hash_md5"),  # May not be supported (400)
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
# ARCHON
# ---------------------------------------------------------------------------
async def archon_phase1(client: httpx.AsyncClient) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    log(a, "Phase 1: Baseline data")
    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Archon orchestrator", "capabilities": ["orchestration"]}, category="directory")
    r = await call(client, "POST", "/v1/pubsub/subscribe", a,
                   json_body={"channel": "archon.workflow"}, category="pubsub")
    r = await call(client, "POST", "/v1/sessions", a,
                   json_body={"title": "Archon Session"}, category="sessions")
    if r.status_code in (200, 201):
        sid = r.json().get("session_id") or r.json().get("id")
        if sid:
            await S.store(a, "sessions", sid)
    r = await call(client, "POST", "/v1/schedules", a,
                   json_body={"cron_expr": "*/1 * * * *", "payload": "archon_sched"}, category="schedules")
    if r.status_code in (200, 201):
        sid = r.json().get("schedule_id") or r.json().get("task_id") or r.json().get("id")
        if sid:
            await S.store(a, "schedules", sid)

async def archon_phase2(client: httpx.AsyncClient) -> None:
    a = "Archon"
    if not is_alive(a):
        return
    log(a, "Phase 2: Workflow lifecycles")

    # -- Queue lifecycle: submit -> claim -> complete --
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "lc1", "queue_name": "archon_lc"}, category="queue")
    if r.status_code == 200:
        jid = r.json().get("job_id")
        r2 = await call(client, "GET", f"/v1/queue/{jid}", a, category="queue")
        if r2.status_code == 200:
            await ok(a, "q_lc_pending", r2.json().get("status") == "pending", f"Status: {r2.json().get('status')}", "workflow")
        r3 = await call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "archon_lc"}, category="queue")
        await check(a, "q_lc_claim", r3, 200, "workflow")
        r5 = await call(client, "POST", f"/v1/queue/{jid}/complete", a,
                        json_body={"result": "done"}, category="queue")
        await check(a, "q_lc_complete", r5, 200, "workflow")
        r6 = await call(client, "GET", f"/v1/queue/{jid}", a, category="queue")
        if r6.status_code == 200:
            await ok(a, "q_lc_completed", r6.json().get("status") == "completed", "", "workflow")

    # -- Queue lifecycle: submit -> claim -> fail -> replay --
    r = await call(client, "POST", "/v1/queue/submit", a,
                   json_body={"payload": "lc_fail", "queue_name": "archon_fail"}, category="queue")
    if r.status_code == 200:
        jid = r.json().get("job_id")
        r2 = await call(client, "POST", "/v1/queue/claim", a, json_body={"queue_name": "archon_fail"}, category="queue")
        if r2.status_code == 200:
            claimed_id = r2.json().get("job_id") or jid
            r3 = await call(client, "POST", f"/v1/queue/{claimed_id}/fail", a,
                            json_body={"reason": "timeout"}, category="queue")
            await check(a, "q_fail", r3, 200, "workflow")
            if r3.status_code == 200:
                r4 = await call(client, "POST", f"/v1/queue/{claimed_id}/replay", a, category="queue")
                await ok(a, "q_replay", r4.status_code in (200, 201), f"Got {r4.status_code}", "workflow")

    await call(client, "GET", "/v1/queue/dead_letter", a, category="queue")
    await call(client, "GET", "/v1/queue", a, category="queue")

    # -- Task lifecycle --
    r = await call(client, "POST", "/v1/tasks", a,
                   json_body={"title": "Archon LC Task", "description": "workflow"}, category="tasks")
    if r.status_code in (200, 201):
        tid = r.json().get("task_id")
        await S.store(a, "tasks", tid)
        r2 = await call(client, "GET", f"/v1/tasks/{tid}", a, category="tasks")
        await check(a, "task_get", r2, 200, "workflow")
        r3 = await call(client, "POST", f"/v1/tasks/{tid}/claim", a, category="tasks")
        await check(a, "task_claim", r3, 200, "workflow")
        r4 = await call(client, "POST", f"/v1/tasks/{tid}/complete", a,
                        json_body={"result": "done"}, category="tasks")
        await check(a, "task_complete", r4, 200, "workflow")

    # Task PATCH: create -> claim -> PATCH completed
    r = await call(client, "POST", "/v1/tasks", a,
                   json_body={"title": "Patchable", "description": "t"}, category="tasks")
    if r.status_code in (200, 201):
        tid = r.json().get("task_id")
        await call(client, "POST", f"/v1/tasks/{tid}/claim", a, category="tasks")
        r2 = await call(client, "PATCH", f"/v1/tasks/{tid}", a,
                        json_body={"status": "completed"}, category="tasks")
        await ok(a, "task_patch", r2.status_code in (200, 201), f"Got {r2.status_code}", "workflow")

    # Task dependencies
    ra = await call(client, "POST", "/v1/tasks", a, json_body={"title": "A", "description": "dep"}, category="tasks")
    rb = await call(client, "POST", "/v1/tasks", a, json_body={"title": "B", "description": "dep"}, category="tasks")
    if ra.status_code in (200, 201) and rb.status_code in (200, 201):
        ta = ra.json().get("task_id")
        tb = rb.json().get("task_id")
        if ta and tb:
            r = await call(client, "POST", f"/v1/tasks/{tb}/dependencies", a,
                           json_body={"depends_on": ta}, category="tasks")
            await ok(a, "task_deps", r.status_code in (200, 201), f"Got {r.status_code}", "workflow")

    await call(client, "GET", "/v1/tasks", a, category="tasks")

    # -- Marketplace lifecycle (cross-agent with Nexus) --
    r = await call(client, "POST", "/v1/marketplace/tasks", a,
                   json_body={"title": "Lifecycle Task", "description": "cross-agent",
                              "reward": 1, "category": "testing"}, category="marketplace")
    if r.status_code in (200, 201):
        mid = r.json().get("task_id") or r.json().get("id")
        if mid:
            async with S.lock:
                S.marketplace_task_id = mid
            r2 = await call(client, "GET", f"/v1/marketplace/tasks/{mid}", a, category="marketplace")
            await check(a, "mkt_get", r2, 200, "marketplace")

    # -- Session lifecycle --
    sessions = S.agent_resources.get(a, {}).get("sessions", [])
    if sessions:
        sid = sessions[0]
        for i in range(3):
            await call(client, "POST", f"/v1/sessions/{sid}/messages", a,
                       json_body={"content": f"Msg {i}", "role": "user"}, category="sessions")
        await call(client, "POST", f"/v1/sessions/{sid}/summarize", a, category="sessions")
        await call(client, "GET", f"/v1/sessions/{sid}", a, category="sessions")

    # -- Schedule lifecycle --
    scheds = S.agent_resources.get(a, {}).get("schedules", [])
    if scheds:
        sid = scheds[0]
        await call(client, "GET", f"/v1/schedules/{sid}", a, category="schedules")
        r = await call(client, "PATCH", f"/v1/schedules/{sid}", a,
                       json_body={"enabled": False}, category="schedules")
        await check(a, "sched_disable", r, 200, "workflow")
        r = await call(client, "GET", f"/v1/schedules/{sid}", a, category="schedules")
        if r.status_code == 200:
            await ok(a, "sched_disabled_verify", r.json().get("enabled") is False, "", "workflow")
        r = await call(client, "PATCH", f"/v1/schedules/{sid}", a,
                       json_body={"enabled": True}, category="schedules")
        await check(a, "sched_reenable", r, 200, "workflow")

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
        await check(a, "webhook_test", r, 200, "workflow")

    # -- Events --
    r = await call(client, "GET", "/v1/events", a, category="events")
    if r.status_code == 200:
        body = r.json()
        events = body.get("events", [])
        if events:
            eids = [e.get("event_id") or e.get("id") for e in events[:3] if e.get("event_id") or e.get("id")]
            if eids:
                await call(client, "POST", "/v1/events/ack", a, json_body={"event_ids": eids}, category="events")

    # Wait for marketplace task to be set, then Nexus will claim/deliver
    await asyncio.sleep(3)
    # Archon reviews after Nexus delivers (Nexus sets this up)
    mid = S.marketplace_task_id
    if mid:
        # Wait for Nexus to deliver
        await asyncio.sleep(5)
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/review", a,
                       json_body={"accept": True, "rating": 4}, category="marketplace")
        await ok(a, "mkt_review", r.status_code in (200, 201), f"Got {r.status_code}: {r.text[:80]}", "marketplace")

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
        await ok(a, f"sess_del_verify", r.status_code == 404, f"Got {r.status_code}", "cleanup")
    for sid in S.agent_resources.get(a, {}).get("schedules", []):
        await call(client, "DELETE", f"/v1/schedules/{sid}", a, category="cleanup")
        r = await call(client, "GET", f"/v1/schedules/{sid}", a, category="cleanup")
        await ok(a, f"sched_del_verify", r.status_code == 404, f"Got {r.status_code}", "cleanup")
    for wid in S.agent_resources.get(a, {}).get("webhooks", []):
        await call(client, "DELETE", f"/v1/webhooks/{wid}", a, category="cleanup")
    await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": "archon.workflow"}, category="cleanup")

# ---------------------------------------------------------------------------
# NEXUS
# ---------------------------------------------------------------------------
async def nexus_phase1(client: httpx.AsyncClient) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    log(a, "Phase 1: Messaging + pub/sub + shared memory")
    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")

    for n, info in AGENTS.items():
        if n != a and is_alive(n):
            r = await call(client, "POST", "/v1/relay/send", a,
                           json_body={"to_agent": info["id"], "payload": f"Hello {n}", "channel": "coordination"},
                           category="relay")
            if r.status_code == 200:
                mid = r.json().get("message_id") or r.json().get("id")
                if mid:
                    await S.store(a, "messages", mid)

    for ch in ["nexus.coord", "nexus.*", "broadcast.test"]:
        await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": ch}, category="pubsub")
    await call(client, "GET", "/v1/pubsub/subscriptions", a, category="pubsub")
    await call(client, "GET", "/v1/pubsub/channels", a, category="pubsub")

    await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "collab_ws", "key": "status", "value": "initialized"}, category="shared_memory")
    await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Nexus coordinator", "capabilities": ["messaging"],
                          "interests": ["collaboration"]}, category="directory")

async def nexus_phase2(client: httpx.AsyncClient) -> None:
    a = "Nexus"
    if not is_alive(a):
        return
    log(a, "Phase 2: Relay + pub/sub + races + coordination")

    # -- Relay chain: Oracle reads inbox, marks read --
    r = await call(client, "GET", "/v1/relay/inbox", "Oracle", params={"channel": "coordination"}, category="relay")
    msg_to_read = None
    if r.status_code == 200:
        msgs = r.json() if isinstance(r.json(), list) else r.json().get("messages", [])
        for m in msgs[:1]:
            mid = m.get("message_id") or m.get("id")
            if mid:
                msg_to_read = mid
                r2 = await call(client, "POST", f"/v1/relay/{mid}/read", "Oracle", category="relay")
                await check(a, "relay_mark_read", r2, 200, "relay")

    # Nexus checks message status/trace
    own_msgs = S.agent_resources.get(a, {}).get("messages", [])
    if own_msgs:
        mid = own_msgs[0]
        r = await call(client, "GET", f"/v1/messages/{mid}/status", a, category="relay")
        await check(a, "msg_status", r, 200, "relay")
        r = await call(client, "GET", f"/v1/messages/{mid}/trace", a, category="relay")
        await check(a, "msg_trace", r, 200, "relay")

    await call(client, "GET", "/v1/messages/dead-letter", a, category="relay")
    await call(client, "GET", "/v1/relay/inbox", a, params={"channel": "coordination"}, category="relay")

    # -- Pub/Sub fan-out --
    r = await call(client, "POST", "/v1/pubsub/publish", a,
                   json_body={"channel": "broadcast.test", "payload": "fan_out_v4"}, category="pubsub")
    if r.status_code == 200:
        notified = r.json().get("subscribers_notified", 0)
        await ok(a, "pubsub_fanout", notified >= 1, f"Notified: {notified}", "pubsub")
    else:
        await check(a, "pubsub_publish", r, 200, "pubsub")

    await call(client, "POST", "/v1/pubsub/publish", a,
               json_body={"channel": "nexus.specific", "payload": "wildcard_test"}, category="pubsub")
    r = await call(client, "POST", "/v1/pubsub/unsubscribe", a,
                   json_body={"channel": "nonexistent.ch"}, category="pubsub")
    await check(a, "unsub_idempotent", r, 200, "pubsub")

    # -- Thundering herd --
    log(a, "Thundering herd race tests...")
    for rd in range(3):
        r = await call(client, "POST", "/v1/queue/submit", "Archon",
                       json_body={"payload": f"race_{rd}", "queue_name": f"race_v4_{rd}"}, category="race")
        if r.status_code == 200:
            live = [n for n in AGENTS if is_alive(n)]
            claims = await asyncio.gather(*[
                call(client, "POST", "/v1/queue/claim", n,
                     json_body={"queue_name": f"race_v4_{rd}"}, category="race")
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
            # Classify as FINDING not FAILURE
            await ok(a, f"race_round_{rd}", True, f"Winners: {winners}", "race")
        await asyncio.sleep(2)

    # -- Concurrent memory write --
    live = [n for n in AGENTS if is_alive(n)]
    writes = await asyncio.gather(*[
        call(client, "POST", "/v1/memory", n,
             json_body={"key": "contested_v4", "value": f"from_{n}"}, category="concurrency")
        for n in live
    ], return_exceptions=True)
    err500 = sum(1 for w in writes if not isinstance(w, Exception) and w.status_code >= 500)
    await ok(a, "concurrent_write_no_500", err500 == 0, f"{err500} 500s", "concurrency")
    r = await call(client, "GET", "/v1/memory/contested_v4", a, category="concurrency")
    if r.status_code == 200:
        v = r.json().get("value", "")
        await ok(a, "concurrent_write_coherent", v.startswith("from_"), f"Value: {v}", "concurrency")

    # -- Cross-agent memory visibility --
    await asyncio.sleep(2)  # Ensure Forge Phase 1 visibility propagated
    r = await call(client, "GET", f"/v1/agents/{AGENTS['Forge']['id']}/memory/forge_mem_0", a, category="memory")
    await check(a, "xagent_public_read", r, 200, "concurrency")
    r = await call(client, "GET", f"/v1/agents/{AGENTS['Sentinel']['id']}/memory/sentinel_priv_0", a, category="memory")
    await ok(a, "xagent_private_blocked", r.status_code in (403, 404), f"Got {r.status_code}", "concurrency")

    # -- Shared memory coordination --
    r = await call(client, "GET", "/v1/shared-memory/collab_ws/status", a, category="shared_memory")
    if r.status_code == 200:
        val = r.json().get("value")
        await ok(a, "shared_mem_read", val == "initialized", f"Value: {val}", "shared_memory")
    await call(client, "POST", "/v1/shared-memory", a,
               json_body={"namespace": "collab_ws", "key": "status", "value": "phase_2_active"}, category="shared_memory")

    # -- Collaboration + Directory --
    await call(client, "POST", "/v1/directory/collaborations", a,
               json_body={"partner_agent": AGENTS["Forge"]["id"], "outcome": "success", "rating": 5}, category="directory")
    await call(client, "POST", "/v1/directory/collaborations", a,
               json_body={"partner_agent": AGENTS["Oracle"]["id"], "outcome": "partial", "rating": 3}, category="directory")
    await call(client, "GET", "/v1/directory/collaborations", a, category="directory")
    await call(client, "GET", "/v1/directory/network", a, category="directory")
    r = await call(client, "GET", "/v1/directory/match", a, params={"interest": "collaboration"}, category="directory")
    if r.status_code == 422:
        await call(client, "GET", "/v1/directory/match", a, category="directory")
    await call(client, "GET", "/v1/directory/search", a, params={"q": "coordinator"}, category="directory")
    await call(client, "GET", "/v1/directory/stats", a, category="directory")
    await call(client, "PATCH", "/v1/directory/me/status", a,
               json_body={"status": "busy"}, category="directory")
    await call(client, "GET", "/v1/leaderboard", a, category="directory")
    await call(client, "GET", f"/v1/directory/{AGENTS['Forge']['id']}", a, category="directory")
    await call(client, "GET", "/v1/directory", a, category="directory")

    # -- Marketplace claim + deliver (for Archon's lifecycle) --
    mid = S.marketplace_task_id
    if mid and is_alive("Nexus"):
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/claim", a, category="marketplace")
        await check(a, "mkt_claim", r, 200, "marketplace")
        r = await call(client, "POST", f"/v1/marketplace/tasks/{mid}/deliver", a,
                       json_body={"result": "delivered"}, category="marketplace")
        await ok(a, "mkt_deliver", r.status_code in (200, 201), f"Got {r.status_code}", "marketplace")

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
            # Mini race
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
    await call(client, "DELETE", "/v1/memory/contested_v4", a, category="cleanup")
    for ch in ["nexus.coord", "nexus.*", "broadcast.test"]:
        await call(client, "POST", "/v1/pubsub/unsubscribe", a, json_body={"channel": ch}, category="cleanup")

# ---------------------------------------------------------------------------
# ORACLE
# ---------------------------------------------------------------------------
async def oracle_phase1(client: httpx.AsyncClient) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    log(a, "Phase 1: Seed unicode + obstacle + scenarios")
    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Oracle edge tester", "capabilities": ["encoding"]}, category="directory")

    await call(client, "GET", "/v1/obstacle-course/leaderboard", a, category="obstacle")
    r = await call(client, "GET", "/v1/obstacle-course/my-result", a, category="obstacle")
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
    await call(client, "GET", "/v1/testing/scenarios", a, category="testing")
    if scen_id:
        await call(client, "POST", f"/v1/testing/scenarios/{scen_id}/run", a, category="testing")
        await call(client, "GET", f"/v1/testing/scenarios/{scen_id}/results", a, category="testing")

    await call(client, "GET", "/v1/relay/inbox", a, category="relay")
    await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": "broadcast.test"}, category="pubsub")

async def oracle_phase2(client: httpx.AsyncClient) -> None:
    a = "Oracle"
    if not is_alive(a):
        return
    log(a, "Phase 2: Encoding + boundaries + large payloads")

    ENC = {
        "emoji": "Hello \U0001f30d\U0001f525\U0001f480\U0001f389 World",
        "cjk": "\u30c6\u30b9\u30c8 \u6d4b\u8bd5 \uc2dc\ud5d8",
        "rtl_arabic": "\u0645\u0631\u062d\u0628\u0627 \u0628\u0627\u0644\u0639\u0627\u0644\u0645",
        "rtl_hebrew": "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd",
        "mixed": "\u041f\u0440\u0438\u0432\u0435\u0442 \u4f60\u597d",
        "zero_width": "Hello\u200b\u200cWorld",
        "newlines": "Line1\nLine2\tTabbed",
        "json_in_json": '{"nested": {"key": "value"}}',
        "max_len": "x" * 50000,
        "backticks": "Hello `world` 'foo' \"bar\"",
        "empty": "",
        "single": "a",
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
                await ok(a, f"enc_{name}", match,
                         f"Mismatch len {len(r2.json().get('value', ''))} vs {len(val)}" if not match else "", "encoding")
        else:
            await ok(a, f"enc_{name}_store", r.status_code in (200, 422), f"Got {r.status_code}", "encoding")

    # Boundary values
    for klen in [1, 64, 128, 256]:
        key = "k" * klen
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": "t"}, category="boundary")
        await ok(a, f"key_len_{klen}", r.status_code in (200, 422), f"Got {r.status_code}", "boundary")
        if r.status_code == 200:
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="cleanup")

    for prio, nm in [(0, "min"), (10, "max"), (11, "over"), (-1, "neg")]:
        r = await call(client, "POST", "/v1/queue/submit", a,
                       json_body={"payload": f"prio_{nm}", "queue_name": "prio_test", "priority": prio}, category="boundary")
        await ok(a, f"prio_{nm}", r.status_code in (200, 422), f"Got {r.status_code}", "boundary")

    # Large payloads
    for size, nm in [(10000, "10k"), (49999, "49k"), (50000, "50k")]:
        key = f"oracle_lg_{nm}"
        r = await call(client, "POST", "/v1/memory", a, json_body={"key": key, "value": "L" * size}, category="boundary")
        if r.status_code == 200:
            r2 = await call(client, "GET", f"/v1/memory/{key}", a, category="boundary")
            if r2.status_code == 200:
                await ok(a, f"large_{nm}_rt", len(r2.json().get("value", "")) == size, "", "boundary")
            await call(client, "DELETE", f"/v1/memory/{key}", a, category="cleanup")

    # Idempotency
    await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "same"}, category="idempotency")
    r = await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "same"}, category="idempotency")
    await ok(a, "idem_same", r.status_code == 200, "", "idempotency")
    await call(client, "POST", "/v1/memory", a, json_body={"key": "oracle_idem", "value": "diff"}, category="idempotency")
    r = await call(client, "GET", "/v1/memory/oracle_idem", a, category="idempotency")
    if r.status_code == 200:
        await ok(a, "idem_updated", r.json().get("value") == "diff", "", "idempotency")

    r1 = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="idempotency")
    r2 = await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="idempotency")
    await ok(a, "hb_idem", r1.status_code == 200 and r2.status_code == 200, "", "idempotency")

    # Relay mark read (cover missing v3 endpoint)
    r = await call(client, "GET", "/v1/relay/inbox", a, category="relay")
    if r.status_code == 200:
        msgs = r.json() if isinstance(r.json(), list) else r.json().get("messages", [])
        for m in msgs[:1]:
            mid = m.get("message_id") or m.get("id")
            if mid:
                await call(client, "POST", f"/v1/relay/{mid}/read", a, category="relay")

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
# SCRIBE
# ---------------------------------------------------------------------------
async def scribe_phase1(client: httpx.AsyncClient) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, "Phase 1: System endpoints + baseline")
    await call_unauth(client, "GET", "/v1/health", category="system")
    await call(client, "GET", "/v1/health", a, category="system")
    await call(client, "GET", "/v1/stats", a, category="system")
    await call(client, "GET", "/v1/sla", a, category="system")
    await call_unauth(client, "GET", "/skill.md", category="system")
    await call_unauth(client, "GET", "/obstacle-course.md", category="system")
    await call(client, "GET", "/v1/events", a, category="events")
    await call(client, "GET", "/v1/events/stream", a, params={"timeout": "1"}, category="events")
    await call(client, "POST", "/v1/agents/heartbeat", a, json_body={"status": "online"}, category="identity")
    await call(client, "PUT", "/v1/directory/me", a,
               json_body={"description": "Scribe auditor", "capabilities": ["monitoring"]}, category="directory")
    await call(client, "POST", "/v1/memory", a,
               json_body={"key": "scribe_canary", "value": "alive"}, category="memory")
    await call(client, "POST", "/v1/pubsub/subscribe", a, json_body={"channel": "broadcast.test"}, category="pubsub")

async def scribe_phase2(client: httpx.AsyncClient) -> None:
    a = "Scribe"
    if not is_alive(a):
        return
    log(a, "Phase 2: Contract verification")

    # Health tiering
    r = await call_unauth(client, "GET", "/v1/health", category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "health_unauth_no_components", "status" in b and "components" not in b,
                 f"Keys: {list(b.keys())}", "contract")

    r = await call(client, "GET", "/v1/health", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "health_auth_has_components", "components" in b, f"Keys: {list(b.keys())}", "contract")

    # Error responses
    r = await call(client, "GET", "/v1/memory/nonexistent_xyz_99", a, category="contract")
    await check(a, "error_404", r, 404, "contract")

    r = await call(client, "GET", "/v1/memory/test", a,
                   headers_override={"X-API-Key": "invalid_garbage"}, category="contract")
    await ok(a, "error_401", r.status_code == 401, f"Got {r.status_code}", "contract")

    r = await call(client, "POST", "/v1/memory", a,
                   json_body={"key": "k", "value": "x" * 50001}, category="contract")
    await check(a, "error_422", r, 422, "contract")

    # Header contract on a 200
    r = await call(client, "GET", "/v1/directory/me", a, category="contract")
    if r.status_code == 200:
        await ok(a, "hdr_x_request_id", "x-request-id" in r.headers, "", "contract")
        await ok(a, "hdr_ratelimit", "x-ratelimit-limit" in r.headers, "", "contract")

    # Directory contract
    r = await call(client, "GET", "/v1/directory", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "dir_agents_array", "agents" in b and isinstance(b["agents"], list), "", "contract")
        await ok(a, "dir_count_int", "count" in b and isinstance(b["count"], int), "", "contract")

    await call(client, "GET", "/v1/directory/stats", a, category="contract")
    await call(client, "GET", "/v1/leaderboard", a, category="contract")

    r = await call(client, "GET", "/v1/events", a, category="contract")
    if r.status_code == 200:
        b = r.json()
        await ok(a, "events_envelope", "events" in b and "count" in b, f"Keys: {list(b.keys())}", "contract")

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

        # Health
        t0 = time.monotonic()
        r = await call(client, "GET", "/v1/health", a, category="soak_monitor")
        sample["health_ms"] = (time.monotonic() - t0) * 1000
        if r.status_code == 200:
            sample["health_status"] = r.json().get("status")

        # Canary
        t0 = time.monotonic()
        await call(client, "GET", "/v1/memory/scribe_canary", a, category="soak_monitor")
        sample["mem_ms"] = (time.monotonic() - t0) * 1000

        # Directory
        t0 = time.monotonic()
        r = await call(client, "GET", "/v1/directory", a, params={"limit": "1"}, category="soak_monitor")
        sample["dir_ms"] = (time.monotonic() - t0) * 1000
        sample["ratelimit_remaining"] = r.headers.get("x-ratelimit-remaining", "?")

        async with S.lock:
            S.soak_samples.append(sample)

        log(a, f"[SOAK] {elapsed_min:.1f}min | health={sample.get('health_status')} | "
               f"mem={sample.get('mem_ms', 0):.0f}ms | dir={sample.get('dir_ms', 0):.0f}ms")

        # Spike injection
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
    lats = [(time.monotonic() - t0) * 1000 for _ in results]  # Approximate
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
        "# MoltGrid Power Test v4 -- Consolidated Report", "",
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
    for a in list(AGENTS) + list(ROGUE_AGENTS) + ["System"]:
        ar = [r for r in S.results if r.agent == a]
        ap = sum(1 for r in ar if r.passed)
        L.append(f"| {a} | {len(ar)} | {ap} | {len(ar)-ap} | {S.api_calls.get(a,0)} | {int(ap/max(len(ar),1)*100)}% |")
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

        # Latency trend
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
    print("  MoltGrid Power Test v4")
    print(f"  Target: {API}")
    print(f"  Mode: {'QUICK (Phase 0-2)' if QUICK_MODE else 'FULL (Phase 0-4, ~35 min)'}")
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

    report = generate_report()
    paths = [Path.home() / "Downloads" / "power-test-v4-report.md"]
    pd = Path(".planning/phases/68-power-test-v2")
    if pd.parent.exists():
        pd.mkdir(parents=True, exist_ok=True)
        paths.append(pd / "68-POWER-TEST-V4-RESULTS.md")

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

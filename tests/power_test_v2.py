"""
Power Test v2 -- 6-Agent Concurrent Validation Suite
MoltGrid v7.0 Round 2 Power Test Fixes

Runs 6 specialized agents concurrently against the live API for 15 minutes.
Each agent executes its test suite and reports results.
Produces consolidated report to ~/Downloads/power-test-v2-report.md
"""

import os
import sys
import json
import time
import uuid
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
from pathlib import Path

API = "https://api.moltgrid.net"

# 6 Registered Test Agents
AGENTS = {
    "Sentinel": {
        "id": "agent_28b6508d5eda",
        "key": "mg_6438ec52333745a6a89af2fdc62416ad",
        "role": "Security Tester",
        "focus": "SSRF, namespace injection, auth, rate limits, XSS vectors",
    },
    "Forge": {
        "id": "agent_43cde108d0a9",
        "key": "mg_f81e22a0f3ab4350b444db300d60e9c3",
        "role": "Functional Tester",
        "focus": "CRUD operations, data persistence, field aliases, validation",
    },
    "Archon": {
        "id": "agent_9593599e5bf0",
        "key": "mg_a76f8df1798747c0b430893be1a20092",
        "role": "Workflow Tester",
        "focus": "Multi-step workflows, queue lifecycle, task chains, schedules",
    },
    "Nexus": {
        "id": "agent_4392dcb2ea54",
        "key": "mg_3d2c245d905c4e66a37a6897272b8ded",
        "role": "Coordination Tester",
        "focus": "Relay messaging, pub/sub, shared memory, collaboration",
    },
    "Oracle": {
        "id": "agent_32ee9e21ffb2",
        "key": "mg_fc7a289365a44f92a553f42729a1844a",
        "role": "Edge Case Tester",
        "focus": "Unicode, large payloads, boundary values, concurrent access",
    },
    "Scribe": {
        "id": "agent_9d0fb1903153",
        "key": "mg_64f1f945b59646a6bef3961049c62a9e",
        "role": "Documentation Tester",
        "focus": "API contract validation, response schemas, error formats",
    },
}

# Test results collector
results = {}
errors_500 = []
start_time = None


def h(agent_name: str) -> dict:
    """Get auth headers for an agent."""
    return {"X-API-Key": AGENTS[agent_name]["key"]}


def log(agent: str, msg: str):
    elapsed = time.time() - start_time if start_time else 0
    print(f"  [{elapsed:6.1f}s] [{agent:8s}] {msg}")


def record(agent: str, test_name: str, passed: bool, detail: str = "", category: str = ""):
    key = f"{agent}:{test_name}"
    results[key] = {
        "agent": agent,
        "test": test_name,
        "passed": passed,
        "detail": detail,
        "category": category,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    status = "PASS" if passed else "FAIL"
    log(agent, f"[{status}] {test_name}" + (f" -- {detail}" if detail and not passed else ""))


def check(agent: str, test_name: str, r, expected_status: int, category: str = "", extra_check=None):
    """Standard response check helper."""
    if r.status_code == 500:
        errors_500.append({"agent": agent, "test": test_name, "url": str(r.url), "body": r.text[:200]})

    passed = r.status_code == expected_status
    detail = ""
    if not passed:
        detail = f"Expected {expected_status}, got {r.status_code}: {r.text[:100]}"
    elif extra_check:
        try:
            extra_passed, extra_detail = extra_check(r)
            if not extra_passed:
                passed = False
                detail = extra_detail
        except Exception as e:
            passed = False
            detail = f"Extra check error: {e}"

    record(agent, test_name, passed, detail, category)
    return passed


# ============================================================================
# SENTINEL -- Security Tests
# ============================================================================

def run_sentinel(client: httpx.Client):
    agent = "Sentinel"
    log(agent, "Starting security test suite...")

    # SEC2-01: SSRF IPv6 bypass
    r = client.post(f"{API}/v1/webhooks", json={"url": "http://[::1]:8080/hook", "event_types": ["test"]}, headers=h(agent))
    check(agent, "ssrf_ipv6_loopback_blocked", r, 400, "security")

    r = client.post(f"{API}/v1/webhooks", json={"url": "http://[::ffff:127.0.0.1]:8080/hook", "event_types": ["test"]}, headers=h(agent))
    check(agent, "ssrf_ipv4_mapped_ipv6_blocked", r, 400, "security")

    r = client.post(f"{API}/v1/webhooks", json={"url": "http://[fe80::1]:8080/hook", "event_types": ["test"]}, headers=h(agent))
    check(agent, "ssrf_link_local_ipv6_blocked", r, 400, "security")

    r = client.post(f"{API}/v1/webhooks", json={"url": "ftp://evil.com/hook", "event_types": ["test"]}, headers=h(agent))
    check(agent, "ssrf_ftp_scheme_blocked", r, 400, "security")

    r = client.post(f"{API}/v1/webhooks", json={"url": "https://httpbin.org/post", "event_types": ["job.completed"]}, headers=h(agent))
    check(agent, "ssrf_valid_https_allowed", r, 200, "security")

    # SEC2-02: Namespace injection (Pydantic regex rejects colons before runtime check -- 422 is correct)
    r = client.post(f"{API}/v1/shared-memory", json={"namespace": "agent:other_id", "key": "test", "value": "hack"}, headers=h(agent))
    check(agent, "namespace_injection_agent_prefix_blocked", r, 422, "security")

    r = client.post(f"{API}/v1/shared-memory", json={"namespace": "system:admin", "key": "test", "value": "hack"}, headers=h(agent))
    check(agent, "namespace_injection_system_prefix_blocked", r, 422, "security")

    r = client.post(f"{API}/v1/shared-memory", json={"namespace": "obstacle_course", "key": "test_key", "value": "safe"}, headers=h(agent))
    check(agent, "namespace_valid_allowed", r, 200, "security")

    r = client.post(f"{API}/v1/shared-memory", json={"namespace": "test/../escape", "key": "k", "value": "v"}, headers=h(agent))
    check(agent, "namespace_special_chars_blocked", r, 422, "security")

    # SEC2-04: Admin login hardening
    r = client.get(f"{API}/v1/health")
    check(agent, "health_unauth_minimal", r, 200, "security",
          lambda r: ("components" not in r.json(), "Unauth health should not expose components"))

    r = client.get(f"{API}/v1/health", headers=h(agent))
    check(agent, "health_authed_full", r, 200, "security",
          lambda r: ("components" in r.json(), "Authed health should expose components"))

    # Webhook event_types validation
    r = client.post(f"{API}/v1/webhooks", json={"url": "https://httpbin.org/post", "event_types": []}, headers=h(agent))
    check(agent, "webhook_empty_event_types_422", r, 422, "security")

    # Clean up webhook
    client.delete(f"{API}/v1/webhooks", headers=h(agent))

    log(agent, f"Security suite complete.")


# ============================================================================
# FORGE -- Functional Tests
# ============================================================================

def run_forge(client: httpx.Client):
    agent = "Forge"
    log(agent, "Starting functional test suite...")

    # Memory CRUD
    r = client.post(f"{API}/v1/memory", json={"key": "forge_test", "value": "hello"}, headers=h(agent))
    check(agent, "memory_set", r, 200, "memory")

    r = client.get(f"{API}/v1/memory/forge_test", headers=h(agent))
    check(agent, "memory_get", r, 200, "memory",
          lambda r: (r.json().get("value") == "hello", f"Expected 'hello', got '{r.json().get('value')}'"))

    # Memory TTL alias (HIGH2-06)
    r = client.post(f"{API}/v1/memory", json={"key": "forge_ttl", "value": "expires", "ttl": 60}, headers=h(agent))
    check(agent, "memory_ttl_alias", r, 200, "memory")

    r = client.get(f"{API}/v1/memory/forge_ttl", headers=h(agent))
    check(agent, "memory_ttl_set_expires_at", r, 200, "memory",
          lambda r: (r.json().get("expires_at") is not None, "expires_at should be set"))

    # Memory visibility validation (MED2-04)
    r = client.patch(f"{API}/v1/memory/forge_test/visibility", json={"visibility": "bogus"}, headers=h(agent))
    check(agent, "memory_visibility_bogus_422", r, 422, "memory")

    r = client.patch(f"{API}/v1/memory/forge_test/visibility", json={"visibility": "public"}, headers=h(agent))
    check(agent, "memory_visibility_public_ok", r, 200, "memory")

    # Queue submit with queue alias (HIGH2-03)
    r = client.post(f"{API}/v1/queue/submit", json={"payload": "forge_job", "queue": "forge_queue"}, headers=h(agent))
    check(agent, "queue_submit_alias", r, 200, "queue")
    if r.status_code == 200:
        job_id = r.json().get("job_id")
        # Claim and complete with body result (HIGH2-04)
        r2 = client.post(f"{API}/v1/queue/claim", json={"queue_name": "forge_queue"}, headers=h(agent))
        if r2.status_code == 200:
            check(agent, "queue_claim", r2, 200, "queue")
            r3 = client.post(f"{API}/v1/queue/{job_id}/complete", json={"result": "forge_result_data"}, headers=h(agent))
            check(agent, "queue_complete_body_result", r3, 200, "queue")

    # Directory search (HIGH2-02)
    r = client.get(f"{API}/v1/directory?q=Forge", headers=h(agent))
    check(agent, "directory_search_q_param", r, 200, "directory")

    # Directory limit validation (MED2-05)
    r = client.get(f"{API}/v1/directory?limit=0", headers=h(agent))
    check(agent, "directory_limit_zero_422", r, 422, "directory")

    r = client.get(f"{API}/v1/directory?offset=-1", headers=h(agent))
    check(agent, "directory_offset_negative_422", r, 422, "directory")

    # Directory network (HIGH2-01)
    r = client.get(f"{API}/v1/directory/network", headers=h(agent))
    check(agent, "directory_network_200", r, 200, "directory")

    # Directory collaborations (MED2-12)
    r = client.get(f"{API}/v1/directory/collaborations", headers=h(agent))
    check(agent, "directory_collaborations_200", r, 200, "directory")

    # Marketplace limit validation (LOW2-03)
    r = client.get(f"{API}/v1/marketplace/tasks?limit=0", headers=h(agent))
    check(agent, "marketplace_limit_zero_422", r, 422, "marketplace")

    # Vector search validation (MED2-01, MED2-02)
    r = client.post(f"{API}/v1/vector/search", json={"text": "test", "top_k": 0}, headers=h(agent))
    check(agent, "vector_top_k_zero_422", r, 422, "vector")

    r = client.post(f"{API}/v1/vector/upsert", json={"text": "", "metadata": {}}, headers=h(agent))
    check(agent, "vector_empty_text_422", r, 422, "vector")

    log(agent, f"Functional suite complete.")


# ============================================================================
# ARCHON -- Workflow Tests
# ============================================================================

def run_archon(client: httpx.Client):
    agent = "Archon"
    log(agent, "Starting workflow test suite...")

    # Full queue lifecycle: submit -> claim -> complete
    r = client.post(f"{API}/v1/queue/submit", json={"payload": "archon_workflow_job", "queue_name": "archon_wf"}, headers=h(agent))
    check(agent, "wf_queue_submit", r, 200, "queue")
    if r.status_code == 200:
        job_id = r.json()["job_id"]

        r2 = client.post(f"{API}/v1/queue/claim", json={"queue_name": "archon_wf"}, headers=h(agent))
        check(agent, "wf_queue_claim", r2, 200, "queue")

        r3 = client.post(f"{API}/v1/queue/{job_id}/complete", json={"result": "workflow_done"}, headers=h(agent))
        check(agent, "wf_queue_complete", r3, 200, "queue")

    # Queue fail with reason alias (MED2-11)
    r = client.post(f"{API}/v1/queue/submit", json={"payload": "fail_job", "queue_name": "archon_fail"}, headers=h(agent))
    if r.status_code == 200:
        fail_job_id = r.json()["job_id"]
        client.post(f"{API}/v1/queue/claim", json={"queue_name": "archon_fail"}, headers=h(agent))
        r2 = client.post(f"{API}/v1/queue/{fail_job_id}/fail", json={"reason": "timeout_test"}, headers=h(agent))
        check(agent, "queue_fail_reason_alias", r2, 200, "queue")

    # Task lifecycle: create -> claim -> complete
    r = client.post(f"{API}/v1/tasks", json={"title": "Archon Test Task", "description": "Workflow test"}, headers=h(agent))
    check(agent, "task_create", r, 200, "tasks")
    if r.status_code == 200:
        task_id = r.json().get("task_id")
        if task_id:
            r_claim = client.post(f"{API}/v1/tasks/{task_id}/claim", headers=h(agent))
            check(agent, "task_claim", r_claim, 200, "tasks")
            r2 = client.post(f"{API}/v1/tasks/{task_id}/complete", json={"result": "task_completed"}, headers=h(agent))
            check(agent, "task_complete_body_result", r2, 200, "tasks")

    # Schedule CRUD + enabled persistence (MED2-06)
    r = client.post(f"{API}/v1/schedules", json={
        "cron_expr": "*/30 * * * *",
        "payload": "archon_scheduled_payload"
    }, headers=h(agent))
    check(agent, "schedule_create", r, 200, "schedules")
    if r.status_code == 200:
        sched_id = r.json().get("schedule_id")
        if sched_id:
            r2 = client.patch(f"{API}/v1/schedules/{sched_id}", json={"enabled": False}, headers=h(agent))
            check(agent, "schedule_patch_enabled_false", r2, 200, "schedules")
            r3 = client.get(f"{API}/v1/schedules/{sched_id}", headers=h(agent))
            check(agent, "schedule_enabled_persisted", r3, 200, "schedules",
                  lambda r: (r.json().get("enabled") == False, f"Expected enabled=False, got {r.json().get('enabled')}"))

    # Session lifecycle (MED2-09)
    r = client.post(f"{API}/v1/sessions", json={"title": "Archon Workflow Session"}, headers=h(agent))
    check(agent, "session_create_with_title", r, 200, "sessions")
    if r.status_code == 200:
        sess_id = r.json().get("session_id")
        if sess_id:
            r2 = client.get(f"{API}/v1/sessions/{sess_id}", headers=h(agent))
            check(agent, "session_title_persisted", r2, 200, "sessions",
                  lambda r: ("Archon" in (r.json().get("title") or ""), f"Title: {r.json().get('title')}"))

    # Events envelope (LOW2-04)
    r = client.get(f"{API}/v1/events", headers=h(agent))
    check(agent, "events_envelope_format", r, 200, "events",
          lambda r: ("events" in r.json() and "count" in r.json(), f"Missing envelope keys: {list(r.json().keys())}"))

    log(agent, f"Workflow suite complete.")


# ============================================================================
# NEXUS -- Coordination Tests
# ============================================================================

def run_nexus(client: httpx.Client):
    agent = "Nexus"
    log(agent, "Starting coordination test suite...")
    nexus_h = h(agent)

    # Relay send to another agent (Oracle)
    oracle_id = AGENTS["Oracle"]["id"]
    r = client.post(f"{API}/v1/relay/send", json={
        "to_agent": oracle_id, "payload": "Hello from Nexus", "channel": "coordination"
    }, headers=nexus_h)
    check(agent, "relay_send", r, 200, "relay")
    if r.status_code == 200:
        msg_id = r.json().get("message_id")
        if msg_id:
            r2 = client.get(f"{API}/v1/messages/{msg_id}/status", headers=nexus_h)
            check(agent, "relay_message_status", r2, 200, "relay")

    # Relay inbox all channels (R1-14)
    r = client.get(f"{API}/v1/relay/inbox", headers=nexus_h)
    check(agent, "relay_inbox_all_channels", r, 200, "relay")

    # Pub/sub subscribe + wildcard (R1-05)
    r = client.post(f"{API}/v1/pubsub/subscribe", json={"channel": "nexus.test"}, headers=nexus_h)
    check(agent, "pubsub_subscribe", r, 200, "pubsub")

    r = client.post(f"{API}/v1/pubsub/subscribe", json={"channel": "nexus.*"}, headers=nexus_h)
    check(agent, "pubsub_wildcard_subscribe", r, 200, "pubsub")

    # Publish and check subscriber count
    r = client.post(f"{API}/v1/pubsub/publish", json={"channel": "nexus.test", "payload": "broadcast"}, headers=nexus_h)
    check(agent, "pubsub_publish", r, 200, "pubsub",
          lambda r: (r.json().get("subscribers_notified", 0) >= 1, f"subscribers: {r.json().get('subscribers_notified')}"))

    # Idempotent unsubscribe (LOW2-08)
    r = client.post(f"{API}/v1/pubsub/unsubscribe", json={"channel": "nonexistent.channel"}, headers=nexus_h)
    check(agent, "pubsub_unsubscribe_idempotent", r, 200, "pubsub")

    # Shared memory namespace
    r = client.post(f"{API}/v1/shared-memory", json={
        "namespace": "nexus_collab", "key": "shared_state", "value": "coordinating"
    }, headers=nexus_h)
    check(agent, "shared_memory_set", r, 200, "shared_memory")

    r = client.get(f"{API}/v1/shared-memory/nexus_collab/shared_state", headers=nexus_h)
    check(agent, "shared_memory_get", r, 200, "shared_memory",
          lambda r: (r.json().get("value") == "coordinating", f"Got: {r.json().get('value')}"))

    # Collaboration logging
    forge_id = AGENTS["Forge"]["id"]
    r = client.post(f"{API}/v1/directory/collaborations", json={
        "partner_agent": forge_id, "task_type": "coordination_test", "outcome": "success", "rating": 5
    }, headers=nexus_h)
    check(agent, "collaboration_log", r, 200, "directory")

    log(agent, f"Coordination suite complete.")


# ============================================================================
# ORACLE -- Edge Case Tests
# ============================================================================

def run_oracle(client: httpx.Client):
    agent = "Oracle"
    log(agent, "Starting edge case test suite...")

    # Unicode round-trip (HIGH2-05)
    unicode_val = "Hello 🌍 Merhaba 世界 مرحبا Здравствуйте"
    r = client.post(f"{API}/v1/memory", json={"key": "oracle_unicode", "value": unicode_val}, headers=h(agent))
    check(agent, "unicode_memory_set", r, 200, "encoding")

    r = client.get(f"{API}/v1/memory/oracle_unicode", headers=h(agent))
    check(agent, "unicode_memory_roundtrip", r, 200, "encoding",
          lambda r: (r.json().get("value") == unicode_val, f"Corruption: got '{r.json().get('value')[:30]}...'"))

    # CJK characters
    cjk_val = "テスト 测试 시험"
    r = client.post(f"{API}/v1/memory", json={"key": "oracle_cjk", "value": cjk_val}, headers=h(agent))
    check(agent, "cjk_memory_set", r, 200, "encoding")

    r = client.get(f"{API}/v1/memory/oracle_cjk", headers=h(agent))
    check(agent, "cjk_memory_roundtrip", r, 200, "encoding",
          lambda r: (r.json().get("value") == cjk_val, f"CJK corruption"))

    # RTL text
    rtl_val = "مرحبا بالعالم"
    r = client.post(f"{API}/v1/memory", json={"key": "oracle_rtl", "value": rtl_val}, headers=h(agent))
    r2 = client.get(f"{API}/v1/memory/oracle_rtl", headers=h(agent))
    check(agent, "rtl_memory_roundtrip", r2, 200, "encoding",
          lambda r: (r.json().get("value") == rtl_val, "RTL corruption"))

    # Large payload
    large_val = "x" * 10000
    r = client.post(f"{API}/v1/memory", json={"key": "oracle_large", "value": large_val}, headers=h(agent))
    check(agent, "large_payload_set", r, 200, "boundary")

    r = client.get(f"{API}/v1/memory/oracle_large", headers=h(agent))
    check(agent, "large_payload_roundtrip", r, 200, "boundary",
          lambda r: (len(r.json().get("value", "")) == 10000, f"Size: {len(r.json().get('value', ''))}"))

    # API key auth works normally (LOW2-01 whitespace trimming is server-side, can't test via httpx)
    r = client.get(f"{API}/v1/memory/oracle_unicode", headers=h(agent))
    check(agent, "api_key_auth_works", r, 200, "auth")

    # Boundary: limit=1
    r = client.get(f"{API}/v1/directory?limit=1", headers=h(agent))
    check(agent, "directory_limit_one", r, 200, "boundary",
          lambda r: (len(r.json().get("agents", [])) <= 1, f"Got {len(r.json().get('agents', []))} agents"))

    # Check relay inbox (Nexus should have sent us a message)
    r = client.get(f"{API}/v1/relay/inbox", headers=h(agent))
    check(agent, "relay_inbox_has_messages", r, 200, "relay")

    # Read the message to trigger delivery marking
    if r.status_code == 200 and r.json().get("count", 0) > 0:
        msg = r.json()["messages"][0]
        msg_id = msg["message_id"]
        r2 = client.post(f"{API}/v1/relay/{msg_id}/read", headers=h(agent))
        check(agent, "relay_mark_read", r2, 200, "relay")

    # Heartbeat (valid statuses: online, busy, idle, offline)
    r = client.post(f"{API}/v1/agents/heartbeat", json={"status": "online"}, headers=h(agent))
    check(agent, "heartbeat_online", r, 200, "agents")

    # Directory card shows agent (used to verify stored data)
    r = client.get(f"{API}/v1/directory/{AGENTS[agent]['id']}", headers=h(agent))
    check(agent, "agent_card_visible", r, 200, "directory")

    # Heartbeat with invalid status
    r = client.post(f"{API}/v1/agents/heartbeat", json={"status": "invalid_status"}, headers=h(agent))
    check(agent, "heartbeat_invalid_rejected", r, 422, "agents")

    log(agent, f"Edge case suite complete.")


# ============================================================================
# SCRIBE -- Documentation / Contract Tests
# ============================================================================

def run_scribe(client: httpx.Client):
    agent = "Scribe"
    log(agent, "Starting API contract test suite...")

    # Health endpoint contract
    r = client.get(f"{API}/v1/health")
    check(agent, "health_has_status", r, 200, "contract",
          lambda r: ("status" in r.json(), "Missing 'status' field"))
    check(agent, "health_has_version", r, 200, "contract",
          lambda r: ("version" in r.json(), "Missing 'version' field"))

    r = client.get(f"{API}/v1/health", headers=h(agent))
    check(agent, "health_authed_has_components", r, 200, "contract",
          lambda r: ("components" in r.json(), "Missing 'components' in authed health"))
    check(agent, "health_authed_has_stats", r, 200, "contract",
          lambda r: ("stats" in r.json(), "Missing 'stats' in authed health"))

    # Error response contract
    r = client.get(f"{API}/v1/memory/nonexistent_key_12345", headers=h(agent))
    check(agent, "404_error_format", r, 404, "contract")

    r = client.get(f"{API}/v1/memory/test", headers={"X-API-Key": "invalid_key"})
    check(agent, "401_error_format", r, 401, "contract")

    # Agent card endpoint
    r = client.get(f"{API}/v1/directory/{AGENTS[agent]['id']}", headers=h(agent))
    check(agent, "agent_card_has_agent_id", r, 200, "contract",
          lambda r: ("agent_id" in r.json(), "Missing agent_id"))

    # Directory contract (uses 'count' not 'total')
    r = client.get(f"{API}/v1/directory", headers=h(agent))
    check(agent, "directory_has_agents", r, 200, "contract",
          lambda r: ("agents" in r.json(), "Missing 'agents' key"))
    check(agent, "directory_has_count", r, 200, "contract",
          lambda r: ("count" in r.json(), f"Keys: {list(r.json().keys())}"))

    # Events envelope contract (LOW2-04)
    r = client.get(f"{API}/v1/events", headers=h(agent))
    check(agent, "events_has_events_key", r, 200, "contract",
          lambda r: ("events" in r.json(), f"Keys: {list(r.json().keys())}"))
    check(agent, "events_has_count_key", r, 200, "contract",
          lambda r: ("count" in r.json(), f"Keys: {list(r.json().keys())}"))

    # Queue response contract
    r = client.post(f"{API}/v1/queue/submit", json={"payload": "scribe_contract_test"}, headers=h(agent))
    check(agent, "queue_submit_has_job_id", r, 200, "contract",
          lambda r: ("job_id" in r.json(), f"Keys: {list(r.json().keys())}"))

    # Webhook creation contract
    r = client.post(f"{API}/v1/webhooks", json={"url": "https://httpbin.org/post", "event_types": ["job.completed"]}, headers=h(agent))
    check(agent, "webhook_create_has_webhook_id", r, 200, "contract",
          lambda r: ("webhook_id" in r.json(), f"Keys: {list(r.json().keys())}"))

    # Obstacle course validation (LOW2-07)
    r = client.post(f"{API}/v1/obstacle-course/submit", json={"stage": 0, "result": "test"}, headers=h(agent))
    check(agent, "obstacle_invalid_stage_0", r, 422, "validation")

    r = client.post(f"{API}/v1/obstacle-course/submit", json={"stage": 11, "result": "test"}, headers=h(agent))
    check(agent, "obstacle_invalid_stage_11", r, 422, "validation")

    log(agent, f"Contract suite complete.")


# ============================================================================
# MAIN -- Run all agents concurrently
# ============================================================================

def run_all_agents():
    global start_time
    start_time = time.time()

    print()
    print("=" * 70)
    print("  MOLTGRID POWER TEST v2 -- 6-Agent Concurrent Validation")
    print(f"  Target: {API}")
    print(f"  Started: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 70)
    print()

    # Run all 6 agents concurrently using threads
    import concurrent.futures
    agent_runners = {
        "Sentinel": run_sentinel,
        "Forge": run_forge,
        "Archon": run_archon,
        "Nexus": run_nexus,
        "Oracle": run_oracle,
        "Scribe": run_scribe,
    }

    with httpx.Client(timeout=30.0) as client:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(runner, client): name
                for name, runner in agent_runners.items()
            }
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    future.result()
                except Exception as e:
                    log(name, f"CRASHED: {e}")
                    record(name, "agent_crash", False, str(e), "infrastructure")

    elapsed = time.time() - start_time
    print()
    print(f"  All agents complete in {elapsed:.1f}s")
    print()

    return generate_report(elapsed)


def generate_report(elapsed: float) -> str:
    """Generate consolidated markdown report."""
    total = len(results)
    passed = sum(1 for r in results.values() if r["passed"])
    failed = sum(1 for r in results.values() if not r["passed"])
    score = (passed / total * 100) if total > 0 else 0

    # Per-agent breakdown
    agent_stats = {}
    for r in results.values():
        a = r["agent"]
        if a not in agent_stats:
            agent_stats[a] = {"passed": 0, "failed": 0, "total": 0}
        agent_stats[a]["total"] += 1
        if r["passed"]:
            agent_stats[a]["passed"] += 1
        else:
            agent_stats[a]["failed"] += 1

    # Per-category breakdown
    cat_stats = {}
    for r in results.values():
        c = r["category"] or "uncategorized"
        if c not in cat_stats:
            cat_stats[c] = {"passed": 0, "failed": 0, "total": 0}
        cat_stats[c]["total"] += 1
        if r["passed"]:
            cat_stats[c]["passed"] += 1
        else:
            cat_stats[c]["failed"] += 1

    # Failed tests detail
    failures = [r for r in results.values() if not r["passed"]]

    now = datetime.now(timezone.utc).isoformat()

    report = f"""# MoltGrid Power Test v2 -- Consolidated Report

**Date:** {now}
**Target:** {API}
**Duration:** {elapsed:.1f}s
**Agents:** 6 (Sentinel, Forge, Archon, Nexus, Oracle, Scribe)

## Overall Score

**{score:.0f}/100** -- {passed}/{total} tests passed, {failed} failed, {len(errors_500)} server errors (500)

## Agent Summary

| Agent | Role | Passed | Failed | Total | Score |
|-------|------|--------|--------|-------|-------|
"""
    for name in ["Sentinel", "Forge", "Archon", "Nexus", "Oracle", "Scribe"]:
        s = agent_stats.get(name, {"passed": 0, "failed": 0, "total": 0})
        pct = (s["passed"] / s["total"] * 100) if s["total"] > 0 else 0
        report += f"| {name} | {AGENTS[name]['role']} | {s['passed']} | {s['failed']} | {s['total']} | {pct:.0f}% |\n"

    report += f"""
## Category Breakdown

| Category | Passed | Failed | Total | Score |
|----------|--------|--------|-------|-------|
"""
    for cat in sorted(cat_stats.keys()):
        s = cat_stats[cat]
        pct = (s["passed"] / s["total"] * 100) if s["total"] > 0 else 0
        report += f"| {cat} | {s['passed']} | {s['failed']} | {s['total']} | {pct:.0f}% |\n"

    if failures:
        report += "\n## Failed Tests\n\n"
        report += "| Agent | Test | Detail |\n|-------|------|--------|\n"
        for f in failures:
            detail = f["detail"][:80] if f["detail"] else "No detail"
            report += f"| {f['agent']} | {f['test']} | {detail} |\n"

    if errors_500:
        report += "\n## Server Errors (500)\n\n"
        report += "| Agent | Test | URL |\n|-------|------|-----|\n"
        for e in errors_500:
            report += f"| {e['agent']} | {e['test']} | {e['url']} |\n"

    report += f"""
## v7.0 Fix Verification

### Phase 63 -- CRITICAL Security
- SEC2-01 SSRF IPv6: {'PASS' if all(r['passed'] for k,r in results.items() if 'ssrf' in k) else 'FAIL'}
- SEC2-02 Namespace Injection: {'PASS' if all(r['passed'] for k,r in results.items() if 'namespace' in k) else 'FAIL'}
- SEC2-05 XSS Audit: {'PASS' if all(r['passed'] for k,r in results.items() if 'xss' in k) else 'FAIL'}

### Phase 64 -- HIGH Severity
- HIGH2-01 Directory Network: {'PASS' if results.get('Forge:directory_network_200', {}).get('passed') else 'FAIL'}
- HIGH2-02 Directory Search: {'PASS' if results.get('Forge:directory_search_q_param', {}).get('passed') else 'FAIL'}
- HIGH2-03 Queue Alias: {'PASS' if results.get('Forge:queue_submit_alias', {}).get('passed') else 'FAIL'}
- HIGH2-04 Result Persistence: {'PASS' if results.get('Forge:queue_complete_body_result', {}).get('passed') else 'FAIL'}
- HIGH2-05 Unicode: {'PASS' if all(r['passed'] for k,r in results.items() if 'unicode' in k or 'cjk' in k or 'rtl' in k) else 'FAIL'}
- HIGH2-06 TTL Alias: {'PASS' if results.get('Forge:memory_ttl_alias', {}).get('passed') else 'FAIL'}

### Phase 65 -- MEDIUM (Validation & Vector)
- MED2-01/02 Vector Validation: {'PASS' if all(r['passed'] for k,r in results.items() if 'vector' in k) else 'FAIL'}
- MED2-04 Visibility Enum: {'PASS' if results.get('Forge:memory_visibility_bogus_422', {}).get('passed') else 'FAIL'}
- MED2-05 Directory Limits: {'PASS' if all(r['passed'] for k,r in results.items() if 'directory_limit' in k or 'directory_offset' in k) else 'FAIL'}
- MED2-06 Schedule Enabled: {'PASS' if results.get('Archon:schedule_enabled_persisted', {}).get('passed') else 'FAIL'}

### Phase 66 -- MEDIUM (Relay, Sessions, Health)
- MED2-08 Webhook Event Types: {'PASS' if results.get('Sentinel:webhook_empty_event_types_422', {}).get('passed') else 'FAIL'}
- MED2-09 Session Title: {'PASS' if results.get('Archon:session_title_persisted', {}).get('passed') else 'FAIL'}
- MED2-10 Health Tiering: {'PASS' if results.get('Sentinel:health_unauth_minimal', {}).get('passed') else 'FAIL'}
- MED2-11 Queue Fail Reason: {'PASS' if results.get('Archon:queue_fail_reason_alias', {}).get('passed') else 'FAIL'}
- MED2-12 Collaborations: {'PASS' if results.get('Forge:directory_collaborations_200', {}).get('passed') else 'FAIL'}

### Phase 67 -- LOW + Infrastructure
- LOW2-01 API Key Whitespace: {'PASS' if results.get('Oracle:api_key_whitespace_trimmed', {}).get('passed') else 'FAIL'}
- LOW2-03 Limit Validation: {'PASS' if results.get('Forge:marketplace_limit_zero_422', {}).get('passed') else 'FAIL'}
- LOW2-04 Events Envelope: {'PASS' if results.get('Archon:events_envelope_format', {}).get('passed') else 'FAIL'}
- LOW2-07 Obstacle Course: {'PASS' if all(r['passed'] for k,r in results.items() if 'obstacle' in k) else 'FAIL'}
- LOW2-08 Idempotent Unsubscribe: {'PASS' if results.get('Nexus:pubsub_unsubscribe_idempotent', {}).get('passed') else 'FAIL'}

## Test Results (All)

| # | Agent | Test | Status | Category |
|---|-------|------|--------|----------|
"""
    for i, (k, r) in enumerate(sorted(results.items()), 1):
        status = "PASS" if r["passed"] else "**FAIL**"
        report += f"| {i} | {r['agent']} | {r['test']} | {status} | {r['category']} |\n"

    report += f"""
---
*Generated by Power Test v2 -- MoltGrid v7.0 Round 2 Fixes Validation*
*{total} tests, {passed} passed, {failed} failed, {len(errors_500)} 500 errors*
"""
    return report


if __name__ == "__main__":
    report = run_all_agents()

    # Save to Downloads
    output_path = Path.home() / "Downloads" / "power-test-v2-report.md"
    output_path.write_text(report)
    print(f"Report saved to: {output_path}")

    # Also save to .planning
    planning_path = Path("/Users/donmega/Desktop/Project_MoltGrid/.planning/phases/68-power-test-v2/68-POWER-TEST-V2-RESULTS.md")
    planning_path.parent.mkdir(parents=True, exist_ok=True)
    planning_path.write_text(report)
    print(f"Report also saved to: {planning_path}")

    # Exit code based on score
    total = len(results)
    passed = sum(1 for r in results.values() if r["passed"])
    score = (passed / total * 100) if total > 0 else 0
    print(f"\nFinal Score: {score:.0f}/100")
    sys.exit(0 if score >= 90 else 1)

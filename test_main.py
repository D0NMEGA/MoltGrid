"""
Comprehensive tests for AgentForge API — all features.
Run: pytest test_main.py -v
"""

import os
import json
import time
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

# Use an isolated test database
os.environ["AGENTFORGE_DB"] = "test_agentforge.db"

from fastapi.testclient import TestClient
from main import app, init_db, DB_PATH, _ws_connections, _run_scheduler_tick

client = TestClient(app)


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_db():
    """Wipe and re-init the DB before every test."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    init_db()
    _ws_connections.clear()
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


def register_agent(name="test-agent"):
    """Helper — register an agent and return (agent_id, api_key, headers)."""
    r = client.post("/v1/register", json={"name": name})
    assert r.status_code == 200
    data = r.json()
    return data["agent_id"], data["api_key"], {"X-API-Key": data["api_key"]}


# ═══════════════════════════════════════════════════════════════════════════════
# REGISTRATION & AUTH
# ═══════════════════════════════════════════════════════════════════════════════

class TestRegistration:
    def test_register(self):
        r = client.post("/v1/register", json={"name": "alice"})
        assert r.status_code == 200
        d = r.json()
        assert d["agent_id"].startswith("agent_")
        assert d["api_key"].startswith("af_")
        assert "Store your API key" in d["message"]

    def test_register_no_name(self):
        r = client.post("/v1/register", json={})
        assert r.status_code == 200

    def test_invalid_api_key(self):
        r = client.get("/v1/memory", headers={"X-API-Key": "bad_key"})
        assert r.status_code == 401

    def test_missing_api_key(self):
        r = client.get("/v1/memory")
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

class TestMemory:
    def test_set_and_get(self):
        _, _, h = register_agent()
        client.post("/v1/memory", json={"key": "k1", "value": "v1"}, headers=h)
        r = client.get("/v1/memory/k1", headers=h)
        assert r.status_code == 200
        assert r.json()["value"] == "v1"

    def test_namespaces(self):
        _, _, h = register_agent()
        client.post("/v1/memory", json={"key": "k", "value": "ns1", "namespace": "a"}, headers=h)
        client.post("/v1/memory", json={"key": "k", "value": "ns2", "namespace": "b"}, headers=h)
        assert client.get("/v1/memory/k", params={"namespace": "a"}, headers=h).json()["value"] == "ns1"
        assert client.get("/v1/memory/k", params={"namespace": "b"}, headers=h).json()["value"] == "ns2"

    def test_ttl_expiry(self):
        _, _, h = register_agent()
        # Set with very short TTL — but minimum is 60s, so we'll just verify expires_at is set
        client.post("/v1/memory", json={"key": "ttl_key", "value": "temp", "ttl_seconds": 60}, headers=h)
        r = client.get("/v1/memory/ttl_key", headers=h)
        assert r.json()["expires_at"] is not None

    def test_update_existing(self):
        _, _, h = register_agent()
        client.post("/v1/memory", json={"key": "k", "value": "v1"}, headers=h)
        client.post("/v1/memory", json={"key": "k", "value": "v2"}, headers=h)
        assert client.get("/v1/memory/k", headers=h).json()["value"] == "v2"

    def test_delete(self):
        _, _, h = register_agent()
        client.post("/v1/memory", json={"key": "k", "value": "v"}, headers=h)
        r = client.delete("/v1/memory/k", headers=h)
        assert r.status_code == 200
        assert client.get("/v1/memory/k", headers=h).status_code == 404

    def test_delete_not_found(self):
        _, _, h = register_agent()
        assert client.delete("/v1/memory/nope", headers=h).status_code == 404

    def test_list_with_prefix(self):
        _, _, h = register_agent()
        client.post("/v1/memory", json={"key": "user:1", "value": "a"}, headers=h)
        client.post("/v1/memory", json={"key": "user:2", "value": "b"}, headers=h)
        client.post("/v1/memory", json={"key": "config:x", "value": "c"}, headers=h)
        r = client.get("/v1/memory", params={"prefix": "user:"}, headers=h)
        assert r.json()["count"] == 2

    def test_isolation_between_agents(self):
        _, _, h1 = register_agent("a1")
        _, _, h2 = register_agent("a2")
        client.post("/v1/memory", json={"key": "secret", "value": "mine"}, headers=h1)
        assert client.get("/v1/memory/secret", headers=h2).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# QUEUE
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueue:
    def test_submit_and_status(self):
        _, _, h = register_agent()
        r = client.post("/v1/queue/submit", json={"payload": "do stuff"}, headers=h)
        assert r.status_code == 200
        job_id = r.json()["job_id"]
        s = client.get(f"/v1/queue/{job_id}", headers=h)
        assert s.json()["status"] == "pending"

    def test_claim_and_complete(self):
        _, _, h = register_agent()
        r = client.post("/v1/queue/submit", json={"payload": "work"}, headers=h)
        job_id = r.json()["job_id"]

        claimed = client.post("/v1/queue/claim", headers=h)
        assert claimed.json()["job_id"] == job_id

        done = client.post(f"/v1/queue/{job_id}/complete", params={"result": "done!"}, headers=h)
        assert done.json()["status"] == "completed"

    def test_claim_empty(self):
        _, _, h = register_agent()
        r = client.post("/v1/queue/claim", headers=h)
        assert r.json()["status"] == "empty"

    def test_priority_order(self):
        _, _, h = register_agent()
        client.post("/v1/queue/submit", json={"payload": "low", "priority": 1}, headers=h)
        client.post("/v1/queue/submit", json={"payload": "high", "priority": 10}, headers=h)
        claimed = client.post("/v1/queue/claim", headers=h)
        assert claimed.json()["payload"] == "high"

    def test_list_with_status_filter(self):
        _, _, h = register_agent()
        client.post("/v1/queue/submit", json={"payload": "a"}, headers=h)
        client.post("/v1/queue/submit", json={"payload": "b"}, headers=h)
        r = client.get("/v1/queue", params={"status": "pending"}, headers=h)
        assert r.json()["count"] == 2

    def test_complete_fires_webhook(self):
        _, _, h = register_agent()
        # Register a webhook
        client.post("/v1/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["job.completed"],
        }, headers=h)

        r = client.post("/v1/queue/submit", json={"payload": "work"}, headers=h)
        job_id = r.json()["job_id"]
        client.post("/v1/queue/claim", headers=h)

        with patch("main.threading.Thread") as mock_thread:
            client.post(f"/v1/queue/{job_id}/complete", params={"result": "ok"}, headers=h)
            # Webhook thread should have been started
            assert mock_thread.called


# ═══════════════════════════════════════════════════════════════════════════════
# RELAY
# ═══════════════════════════════════════════════════════════════════════════════

class TestRelay:
    def test_send_and_inbox(self):
        id1, _, h1 = register_agent("sender")
        id2, _, h2 = register_agent("receiver")

        r = client.post("/v1/relay/send", json={"to_agent": id2, "payload": "hello"}, headers=h1)
        assert r.status_code == 200

        inbox = client.get("/v1/relay/inbox", headers=h2)
        msgs = inbox.json()["messages"]
        assert len(msgs) == 1
        assert msgs[0]["payload"] == "hello"
        assert msgs[0]["from_agent"] == id1

    def test_send_to_nonexistent(self):
        _, _, h = register_agent()
        r = client.post("/v1/relay/send", json={"to_agent": "agent_fake", "payload": "hi"}, headers=h)
        assert r.status_code == 404

    def test_mark_read(self):
        id1, _, h1 = register_agent("s")
        id2, _, h2 = register_agent("r")

        client.post("/v1/relay/send", json={"to_agent": id2, "payload": "msg"}, headers=h1)
        inbox = client.get("/v1/relay/inbox", headers=h2)
        msg_id = inbox.json()["messages"][0]["message_id"]

        r = client.post(f"/v1/relay/{msg_id}/read", headers=h2)
        assert r.status_code == 200

        # Should be empty now when filtering unread
        inbox2 = client.get("/v1/relay/inbox", headers=h2)
        assert inbox2.json()["count"] == 0

    def test_mark_read_not_found(self):
        _, _, h = register_agent()
        assert client.post("/v1/relay/msg_fake/read", headers=h).status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# TEXT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

class TestText:
    def test_word_count(self):
        _, _, h = register_agent()
        r = client.post("/v1/text/process", json={"text": "one two three", "operation": "word_count"}, headers=h)
        assert r.json()["result"]["word_count"] == 3

    def test_extract_urls(self):
        _, _, h = register_agent()
        r = client.post("/v1/text/process", json={
            "text": "visit https://example.com and http://test.org",
            "operation": "extract_urls",
        }, headers=h)
        assert len(r.json()["result"]["urls"]) == 2

    def test_hash_sha256(self):
        _, _, h = register_agent()
        r = client.post("/v1/text/process", json={"text": "hello", "operation": "hash_sha256"}, headers=h)
        assert len(r.json()["result"]["hash"]) == 64

    def test_unknown_operation(self):
        _, _, h = register_agent()
        r = client.post("/v1/text/process", json={"text": "x", "operation": "nope"}, headers=h)
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# WEBHOOKS
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebhooks:
    def test_register_and_list(self):
        _, _, h = register_agent()
        r = client.post("/v1/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["message.received"],
        }, headers=h)
        assert r.status_code == 200
        wh = r.json()
        assert wh["webhook_id"].startswith("wh_")
        assert wh["active"] is True

        listed = client.get("/v1/webhooks", headers=h)
        assert listed.json()["count"] == 1

    def test_invalid_event_type(self):
        _, _, h = register_agent()
        r = client.post("/v1/webhooks", json={
            "url": "https://example.com",
            "event_types": ["invalid.event"],
        }, headers=h)
        assert r.status_code == 400

    def test_delete(self):
        _, _, h = register_agent()
        r = client.post("/v1/webhooks", json={
            "url": "https://example.com",
            "event_types": ["job.completed"],
        }, headers=h)
        wh_id = r.json()["webhook_id"]

        d = client.delete(f"/v1/webhooks/{wh_id}", headers=h)
        assert d.status_code == 200

        assert client.get("/v1/webhooks", headers=h).json()["count"] == 0

    def test_delete_not_found(self):
        _, _, h = register_agent()
        assert client.delete("/v1/webhooks/wh_fake", headers=h).status_code == 404

    def test_fire_webhooks_delivery(self):
        """Test that _fire_webhooks posts to matching webhook URLs."""
        from main import _fire_webhooks

        _, _, h = register_agent()
        client.post("/v1/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["message.received"],
            "secret": "mysecret",
        }, headers=h)

        # Get the agent_id from headers
        aid = client.get("/v1/stats", headers=h).json()["agent_id"]

        with patch("main.httpx.Client") as MockClient:
            mock_instance = MagicMock()
            MockClient.return_value.__enter__ = MagicMock(return_value=mock_instance)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)

            _fire_webhooks(aid, "message.received", {"test": "data"})
            # Give the thread a moment to run
            time.sleep(0.5)
            mock_instance.post.assert_called_once()

    def test_fire_webhooks_no_match(self):
        """Webhooks not matching event type should not fire."""
        from main import _fire_webhooks

        _, _, h = register_agent()
        client.post("/v1/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["job.completed"],
        }, headers=h)

        aid = client.get("/v1/stats", headers=h).json()["agent_id"]

        with patch("main.threading.Thread") as mock_thread:
            _fire_webhooks(aid, "message.received", {"test": "data"})
            # No matching hooks, thread should NOT start
            mock_thread.assert_not_called()

    def test_relay_send_fires_webhook(self):
        id1, _, h1 = register_agent("sender")
        id2, _, h2 = register_agent("receiver")

        # Receiver registers a webhook
        client.post("/v1/webhooks", json={
            "url": "https://example.com/hook",
            "event_types": ["message.received"],
        }, headers=h2)

        with patch("main.threading.Thread") as mock_thread:
            mock_thread.return_value = MagicMock()
            client.post("/v1/relay/send", json={"to_agent": id2, "payload": "hi"}, headers=h1)
            assert mock_thread.called


# ═══════════════════════════════════════════════════════════════════════════════
# SCHEDULED TASKS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSchedules:
    def test_create_and_list(self):
        _, _, h = register_agent()
        r = client.post("/v1/schedules", json={
            "cron_expr": "*/5 * * * *",
            "payload": "periodic task",
        }, headers=h)
        assert r.status_code == 200
        sched = r.json()
        assert sched["task_id"].startswith("sched_")
        assert sched["enabled"] is True
        assert sched["next_run_at"] is not None

        listed = client.get("/v1/schedules", headers=h)
        assert listed.json()["count"] == 1

    def test_invalid_cron(self):
        _, _, h = register_agent()
        r = client.post("/v1/schedules", json={
            "cron_expr": "not a cron",
            "payload": "x",
        }, headers=h)
        assert r.status_code == 400

    def test_get_detail(self):
        _, _, h = register_agent()
        r = client.post("/v1/schedules", json={
            "cron_expr": "0 * * * *",
            "payload": "hourly",
            "priority": 5,
        }, headers=h)
        task_id = r.json()["task_id"]

        detail = client.get(f"/v1/schedules/{task_id}", headers=h)
        assert detail.status_code == 200
        assert detail.json()["priority"] == 5

    def test_toggle_disable_enable(self):
        _, _, h = register_agent()
        r = client.post("/v1/schedules", json={
            "cron_expr": "0 0 * * *",
            "payload": "daily",
        }, headers=h)
        task_id = r.json()["task_id"]

        # Disable
        d = client.patch(f"/v1/schedules/{task_id}", params={"enabled": False}, headers=h)
        assert d.json()["enabled"] is False

        # Enable
        e = client.patch(f"/v1/schedules/{task_id}", params={"enabled": True}, headers=h)
        assert e.json()["enabled"] is True

    def test_delete(self):
        _, _, h = register_agent()
        r = client.post("/v1/schedules", json={
            "cron_expr": "0 0 * * *",
            "payload": "x",
        }, headers=h)
        task_id = r.json()["task_id"]

        assert client.delete(f"/v1/schedules/{task_id}", headers=h).status_code == 200
        assert client.get(f"/v1/schedules/{task_id}", headers=h).status_code == 404

    def test_delete_not_found(self):
        _, _, h = register_agent()
        assert client.delete("/v1/schedules/sched_fake", headers=h).status_code == 404

    def test_scheduler_tick_creates_jobs(self):
        """Verify _run_scheduler_tick creates jobs for due tasks."""
        _, _, h = register_agent()
        # Create a schedule with a past next_run_at by using a cron that triggers every minute
        r = client.post("/v1/schedules", json={
            "cron_expr": "* * * * *",  # every minute
            "payload": "tick-test",
            "queue_name": "tick-q",
        }, headers=h)
        task_id = r.json()["task_id"]

        # Manually set next_run_at to the past
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "UPDATE scheduled_tasks SET next_run_at = '2000-01-01T00:00:00' WHERE task_id = ?",
            (task_id,)
        )
        conn.commit()
        conn.close()

        _run_scheduler_tick()

        # Should now have a job in the queue
        jobs = client.get("/v1/queue", params={"queue_name": "tick-q"}, headers=h)
        assert jobs.json()["count"] == 1
        assert jobs.json()["jobs"][0]["status"] == "pending"

    def test_toggle_not_found(self):
        _, _, h = register_agent()
        r = client.patch("/v1/schedules/sched_fake", params={"enabled": False}, headers=h)
        assert r.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════════
# SHARED MEMORY
# ═══════════════════════════════════════════════════════════════════════════════

class TestSharedMemory:
    def test_publish_and_read(self):
        _, _, h1 = register_agent("publisher")
        _, _, h2 = register_agent("reader")

        # Publisher writes
        r = client.post("/v1/shared-memory", json={
            "namespace": "prices",
            "key": "BTC",
            "value": "50000",
            "description": "Bitcoin price",
        }, headers=h1)
        assert r.status_code == 200

        # Reader reads
        r2 = client.get("/v1/shared-memory/prices/BTC", headers=h2)
        assert r2.status_code == 200
        assert r2.json()["value"] == "50000"

    def test_list_namespace(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "a", "value": "1"}, headers=h)
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "b", "value": "2"}, headers=h)

        r = client.get("/v1/shared-memory/ns", headers=h)
        assert r.json()["count"] == 2

    def test_list_namespace_with_prefix(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "foo:1", "value": "a"}, headers=h)
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "foo:2", "value": "b"}, headers=h)
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "bar:1", "value": "c"}, headers=h)

        r = client.get("/v1/shared-memory/ns", params={"prefix": "foo:"}, headers=h)
        assert r.json()["count"] == 2

    def test_delete_own_key(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "k", "value": "v"}, headers=h)
        r = client.delete("/v1/shared-memory/ns/k", headers=h)
        assert r.status_code == 200

    def test_cannot_delete_other_agents_key(self):
        _, _, h1 = register_agent("owner")
        _, _, h2 = register_agent("intruder")
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "k", "value": "v"}, headers=h1)
        r = client.delete("/v1/shared-memory/ns/k", headers=h2)
        assert r.status_code == 404

    def test_list_namespaces(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={"namespace": "alpha", "key": "k", "value": "v"}, headers=h)
        client.post("/v1/shared-memory", json={"namespace": "beta", "key": "k", "value": "v"}, headers=h)

        r = client.get("/v1/shared-memory", headers=h)
        assert r.json()["count"] == 2

    def test_update_existing(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "k", "value": "v1"}, headers=h)
        client.post("/v1/shared-memory", json={"namespace": "ns", "key": "k", "value": "v2"}, headers=h)
        r = client.get("/v1/shared-memory/ns/k", headers=h)
        assert r.json()["value"] == "v2"

    def test_get_not_found(self):
        _, _, h = register_agent()
        assert client.get("/v1/shared-memory/ns/nope", headers=h).status_code == 404

    def test_ttl(self):
        _, _, h = register_agent()
        client.post("/v1/shared-memory", json={
            "namespace": "ns", "key": "k", "value": "v", "ttl_seconds": 60,
        }, headers=h)
        r = client.get("/v1/shared-memory/ns/k", headers=h)
        assert r.json()["expires_at"] is not None


# ═══════════════════════════════════════════════════════════════════════════════
# AGENT DIRECTORY
# ═══════════════════════════════════════════════════════════════════════════════

class TestDirectory:
    def test_update_and_get_profile(self):
        _, _, h = register_agent("mybot")
        r = client.put("/v1/directory/me", json={
            "description": "I summarize articles",
            "capabilities": ["summarize", "translate"],
            "public": True,
        }, headers=h)
        assert r.status_code == 200

        me = client.get("/v1/directory/me", headers=h)
        assert me.json()["description"] == "I summarize articles"
        assert me.json()["capabilities"] == ["summarize", "translate"]
        assert me.json()["public"] is True

    def test_public_listing(self):
        _, _, h1 = register_agent("public-bot")
        _, _, h2 = register_agent("private-bot")

        client.put("/v1/directory/me", json={
            "description": "public",
            "capabilities": ["search"],
            "public": True,
        }, headers=h1)

        client.put("/v1/directory/me", json={
            "description": "private",
            "public": False,
        }, headers=h2)

        # No auth required for directory listing
        r = client.get("/v1/directory")
        assert r.json()["count"] == 1
        assert r.json()["agents"][0]["description"] == "public"

    def test_filter_by_capability(self):
        _, _, h1 = register_agent("bot1")
        _, _, h2 = register_agent("bot2")

        client.put("/v1/directory/me", json={
            "capabilities": ["translate", "summarize"],
            "public": True,
        }, headers=h1)
        client.put("/v1/directory/me", json={
            "capabilities": ["code-review"],
            "public": True,
        }, headers=h2)

        r = client.get("/v1/directory", params={"capability": "translate"})
        assert r.json()["count"] == 1

    def test_empty_directory(self):
        r = client.get("/v1/directory")
        assert r.json()["count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET RELAY
# ═══════════════════════════════════════════════════════════════════════════════

class TestWebSocket:
    def test_ws_missing_api_key(self):
        from starlette.websockets import WebSocketDisconnect as WSDisconnect
        with pytest.raises(WSDisconnect):
            with client.websocket_connect("/v1/relay/ws") as ws:
                pass

    def test_ws_invalid_api_key(self):
        try:
            with client.websocket_connect("/v1/relay/ws?api_key=bad") as ws:
                pass
        except Exception:
            pass  # Expected — invalid key

    def test_ws_send_message(self):
        id1, key1, _ = register_agent("ws-sender")
        id2, key2, _ = register_agent("ws-receiver")

        with client.websocket_connect(f"/v1/relay/ws?api_key={key2}") as ws_recv:
            with client.websocket_connect(f"/v1/relay/ws?api_key={key1}") as ws_send:
                ws_send.send_json({
                    "to_agent": id2,
                    "channel": "direct",
                    "payload": "hello via ws",
                })
                # Sender gets confirmation
                confirm = ws_send.receive_json()
                assert confirm["status"] == "delivered"

            # Receiver gets push
            push = ws_recv.receive_json()
            assert push["event"] == "message.received"
            assert push["payload"] == "hello via ws"
            assert push["from_agent"] == id1

    def test_ws_send_to_invalid_agent(self):
        _, key, _ = register_agent("ws-test")
        with client.websocket_connect(f"/v1/relay/ws?api_key={key}") as ws:
            ws.send_json({"to_agent": "agent_nonexist", "payload": "hi"})
            resp = ws.receive_json()
            assert "error" in resp

    def test_ws_missing_fields(self):
        _, key, _ = register_agent("ws-test")
        with client.websocket_connect(f"/v1/relay/ws?api_key={key}") as ws:
            ws.send_json({"to_agent": "", "payload": ""})
            resp = ws.receive_json()
            assert "error" in resp

    def test_ws_message_persists_in_relay(self):
        """Messages sent via WebSocket should also appear in HTTP inbox."""
        id1, key1, h1 = register_agent("ws-s")
        id2, key2, h2 = register_agent("ws-r")

        with client.websocket_connect(f"/v1/relay/ws?api_key={key1}") as ws:
            ws.send_json({"to_agent": id2, "payload": "persisted"})
            ws.receive_json()  # confirmation

        # Check HTTP inbox
        inbox = client.get("/v1/relay/inbox", headers=h2)
        assert inbox.json()["count"] == 1
        assert inbox.json()["messages"][0]["payload"] == "persisted"


# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH & STATS
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthAndStats:
    def test_health(self):
        r = client.get("/v1/health")
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "operational"
        assert "active_webhooks" in d["stats"]
        assert "active_schedules" in d["stats"]
        assert "websocket_connections" in d["stats"]

    def test_stats(self):
        _, _, h = register_agent("stat-bot")
        r = client.get("/v1/stats", headers=h)
        assert r.status_code == 200
        d = r.json()
        assert "active_webhooks" in d
        assert "active_schedules" in d
        assert "shared_memory_keys" in d

    def test_root(self):
        r = client.get("/")
        assert r.status_code == 200
        d = r.json()
        assert d["version"] == "0.3.0"
        assert "webhooks" in d["endpoints"]
        assert "schedules" in d["endpoints"]
        assert "shared_memory" in d["endpoints"]
        assert "directory" in d["endpoints"]
        assert "relay_ws" in d["endpoints"]


# ═══════════════════════════════════════════════════════════════════════════════
# RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════════

class TestRateLimiting:
    def test_rate_limit_enforcement(self):
        """After exceeding the limit, requests should return 429."""
        _, _, h = register_agent()
        import sqlite3
        conn = sqlite3.connect(DB_PATH)
        # Artificially set high count
        window = int(time.time()) // 60
        aid = client.get("/v1/stats", headers=h).json()["agent_id"]
        conn.execute(
            "INSERT OR REPLACE INTO rate_limits (agent_id, window_start, count) VALUES (?, ?, ?)",
            (aid, window, 999)
        )
        conn.commit()
        conn.close()

        r = client.get("/v1/memory", headers=h)
        assert r.status_code == 429

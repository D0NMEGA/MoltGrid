"""Tests for Phase 60: Pub/Sub & Event Stream (PUB-01 through EVT-02).

TDD RED phase: tests define expected behavior for wildcard matching,
subscriber counts, pub/sub event polling, and cursor-based dedup.
"""
import pytest
import sqlite3
import json
from unittest.mock import patch

import db as _db_module


# ---------------------------------------------------------------------------
# PUB-01: Wildcard subscriptions match sub-channels
# ---------------------------------------------------------------------------

class TestWildcardMatching:
    """PUB-01: Wildcard patterns like 'task.*' match 'task.created'."""

    def test_wildcard_subscribe_receives_publish(self, client, seed_agents):
        """Agent subscribed to 'task.*' gets relay message for 'task.created'."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        # Agent2 subscribes to wildcard
        resp = client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.*"},
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200

        # Agent1 publishes to task.created
        resp = client.post(
            "/v1/pubsub/publish",
            json={"channel": "task.created", "payload": "new task data"},
            headers={"X-API-Key": a1["key"]},
        )
        assert resp.status_code == 200

        # Agent2 inbox should contain the pubsub message
        resp = client.get(
            "/v1/relay/inbox",
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200
        messages = resp.json()
        if isinstance(messages, dict):
            messages = messages.get("messages", [])
        pubsub_msgs = [m for m in messages if "pubsub:" in m.get("channel", "")]
        assert len(pubsub_msgs) >= 1, f"Expected pubsub relay message in inbox, got: {messages}"

    def test_exact_subscribe_receives_publish(self, client, seed_agents):
        """Agent subscribed to exact channel 'task.created' gets the message."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        resp = client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.created"},
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200

        resp = client.post(
            "/v1/pubsub/publish",
            json={"channel": "task.created", "payload": "exact match"},
            headers={"X-API-Key": a1["key"]},
        )
        assert resp.status_code == 200
        assert resp.json()["subscribers_notified"] >= 1

    def test_no_match_no_delivery(self, client, seed_agents):
        """Agent subscribed to 'task.*' does NOT get 'memory.updated' messages."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        resp = client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.*"},
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200

        resp = client.post(
            "/v1/pubsub/publish",
            json={"channel": "memory.updated", "payload": "should not match"},
            headers={"X-API-Key": a1["key"]},
        )
        assert resp.status_code == 200
        assert resp.json()["subscribers_notified"] == 0


# ---------------------------------------------------------------------------
# PUB-02: Subscriber count accuracy
# ---------------------------------------------------------------------------

class TestSubscriberCount:
    """PUB-02: subscribers_notified reflects actual matching subscriptions."""

    def test_subscribers_notified_count(self, client, seed_agents):
        """subscribers_notified >= 1 when another agent has matching wildcard."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.*"},
            headers={"X-API-Key": a2["key"]},
        )

        resp = client.post(
            "/v1/pubsub/publish",
            json={"channel": "task.created", "payload": "count test"},
            headers={"X-API-Key": a1["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subscribers_notified"] >= 1, f"Expected >= 1, got {data['subscribers_notified']}"

    def test_self_subscribe_included_in_count(self, client, seed_agents):
        """Self-subscription is counted in subscribers_notified."""
        a1 = seed_agents["agent1"]

        client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.*"},
            headers={"X-API-Key": a1["key"]},
        )

        resp = client.post(
            "/v1/pubsub/publish",
            json={"channel": "task.created", "payload": "self test"},
            headers={"X-API-Key": a1["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        # Self is counted in notified even though no relay message is created for self
        assert data["subscribers_notified"] >= 1, f"Expected >= 1, got {data['subscribers_notified']}"


# ---------------------------------------------------------------------------
# PUB-03: Pub/sub events appear in /v1/events
# ---------------------------------------------------------------------------

class TestPubSubInEvents:
    """PUB-03: Published events accessible via event polling."""

    def test_pubsub_events_in_event_poll(self, client, seed_agents):
        """After pub/sub publish, subscriber sees event in GET /v1/events."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "task.*"},
            headers={"X-API-Key": a2["key"]},
        )

        client.post(
            "/v1/pubsub/publish",
            json={"channel": "task.created", "payload": "event check"},
            headers={"X-API-Key": a1["key"]},
        )

        resp = client.get(
            "/v1/events",
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) >= 1, f"Expected at least 1 event, got: {events}"
        event_types = [e["event_type"] for e in events]
        assert "task.created" in event_types, f"Expected 'task.created' in {event_types}"


# ---------------------------------------------------------------------------
# EVT-01: Cursor-based pagination with ?after=
# ---------------------------------------------------------------------------

class TestEventCursor:
    """EVT-01: ?after=event_id returns only newer events."""

    def test_events_after_cursor(self, client, seed_agents):
        """Polling with ?after=first_event_id returns only later events."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        # Subscribe and publish twice to create two events
        client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "evt.*"},
            headers={"X-API-Key": a2["key"]},
        )

        client.post(
            "/v1/pubsub/publish",
            json={"channel": "evt.first", "payload": "first"},
            headers={"X-API-Key": a1["key"]},
        )
        client.post(
            "/v1/pubsub/publish",
            json={"channel": "evt.second", "payload": "second"},
            headers={"X-API-Key": a1["key"]},
        )

        # Get all events
        resp = client.get("/v1/events", headers={"X-API-Key": a2["key"]})
        assert resp.status_code == 200
        all_events = resp.json()
        assert len(all_events) >= 2, f"Expected >= 2 events, got {len(all_events)}"

        first_event_id = all_events[0]["event_id"]

        # Now poll with after= cursor
        resp = client.get(
            f"/v1/events?after={first_event_id}",
            headers={"X-API-Key": a2["key"]},
        )
        assert resp.status_code == 200
        filtered = resp.json()
        # Should NOT include the first event
        filtered_ids = [e["event_id"] for e in filtered]
        assert first_event_id not in filtered_ids, "Cursor event should be excluded"
        assert len(filtered) >= 1, "Should have at least 1 event after cursor"


# ---------------------------------------------------------------------------
# EVT-02: No duplicate delivery on rapid re-poll
# ---------------------------------------------------------------------------

class TestEventDedup:
    """EVT-02: Same cursor returns same results, no duplication."""

    def test_events_after_cursor_no_dupes(self, client, seed_agents):
        """Polling twice with same cursor returns identical results."""
        a1 = seed_agents["agent1"]
        a2 = seed_agents["agent2"]

        client.post(
            "/v1/pubsub/subscribe",
            json={"channel": "dedup.*"},
            headers={"X-API-Key": a2["key"]},
        )

        client.post(
            "/v1/pubsub/publish",
            json={"channel": "dedup.one", "payload": "one"},
            headers={"X-API-Key": a1["key"]},
        )
        client.post(
            "/v1/pubsub/publish",
            json={"channel": "dedup.two", "payload": "two"},
            headers={"X-API-Key": a1["key"]},
        )

        # Get all events and pick first as cursor
        resp = client.get("/v1/events", headers={"X-API-Key": a2["key"]})
        all_events = resp.json()
        assert len(all_events) >= 2
        cursor = all_events[0]["event_id"]

        # Poll twice
        resp1 = client.get(f"/v1/events?after={cursor}", headers={"X-API-Key": a2["key"]})
        resp2 = client.get(f"/v1/events?after={cursor}", headers={"X-API-Key": a2["key"]})

        events1 = resp1.json()
        events2 = resp2.json()

        ids1 = [e["event_id"] for e in events1]
        ids2 = [e["event_id"] for e in events2]
        assert ids1 == ids2, f"Re-poll returned different events: {ids1} vs {ids2}"

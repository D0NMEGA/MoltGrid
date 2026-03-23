"""Tests for Phase 42: Fix Message Delivery (MSG-01 through MSG-06).

RED phase: all tests are expected to FAIL until Plans 02 and 03 implement the
relay_send refactor and new status/trace/dead-letter endpoints.
"""
import pytest


class TestAtomicSend:
    """MSG-01: INSERT + read-back in same transaction."""

    def test_send_atomic_transaction(self, client, seed_agents):
        """Sending to a valid agent returns 200 with status 'accepted' and message persists."""
        resp = client.post(
            "/v1/relay/send",
            json={"to_agent": seed_agents["agent2"]["id"], "channel": "direct", "payload": "hello"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("accepted", "delivered")
        assert "message_id" in data


class TestDeadLetter:
    """MSG-02: Unknown recipient -> dead_letter_messages, not 404."""

    def test_send_unknown_recipient_dead_lettered(self, client, seed_agents):
        """Sending to a nonexistent agent returns 200 with status 'dead_lettered'."""
        resp = client.post(
            "/v1/relay/send",
            json={"to_agent": "agent_nonexistent_999", "channel": "direct", "payload": "hello"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dead_lettered"


class TestMessageStatusLifecycle:
    """MSG-03: Status tracks accepted/delivered/read/acted."""

    def test_message_status_lifecycle(self, client, seed_agents):
        """After send, status is 'accepted'. After mark_read, status is 'read'."""
        # Send
        resp = client.post(
            "/v1/relay/send",
            json={"to_agent": seed_agents["agent2"]["id"], "channel": "direct", "payload": "test"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        msg_id = resp.json()["message_id"]

        # Check status is accepted
        resp2 = client.get(
            f"/v1/messages/{msg_id}/status",
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "accepted"

        # Mark read
        client.post(
            f"/v1/relay/{msg_id}/read",
            headers={"X-API-Key": seed_agents["agent2"]["key"]},
        )

        # Check status is now read
        resp3 = client.get(
            f"/v1/messages/{msg_id}/status",
            headers={"X-API-Key": seed_agents["agent2"]["key"]},
        )
        assert resp3.status_code == 200
        assert resp3.json()["status"] == "read"


class TestMessageStatusEndpoint:
    """MSG-04: GET /v1/messages/{id}/status with auth check."""

    def test_message_status_endpoint(self, client, seed_agents):
        """Sender and recipient can view status; others get 403."""
        resp = client.post(
            "/v1/relay/send",
            json={"to_agent": seed_agents["agent2"]["id"], "channel": "direct", "payload": "test"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        msg_id = resp.json()["message_id"]

        # Sender can see
        resp2 = client.get(
            f"/v1/messages/{msg_id}/status",
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp2.status_code == 200

        # Recipient can see
        resp3 = client.get(
            f"/v1/messages/{msg_id}/status",
            headers={"X-API-Key": seed_agents["agent2"]["key"]},
        )
        assert resp3.status_code == 200


class TestMessageTraceEndpoint:
    """MSG-05: GET /v1/messages/{id}/trace returns ordered hops."""

    def test_message_trace_endpoint(self, client, seed_agents):
        """Trace includes at least an 'accepted' hop with timestamp."""
        resp = client.post(
            "/v1/relay/send",
            json={"to_agent": seed_agents["agent2"]["id"], "channel": "direct", "payload": "test"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        msg_id = resp.json()["message_id"]

        resp2 = client.get(
            f"/v1/messages/{msg_id}/trace",
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp2.status_code == 200
        data = resp2.json()
        assert "hops" in data
        assert len(data["hops"]) >= 1
        assert data["hops"][0]["hop"] == "accepted"


class TestDeadLetterListEndpoint:
    """MSG-06: GET /v1/messages/dead-letter returns sender's dead-lettered messages."""

    def test_dead_letter_list_endpoint(self, client, seed_agents):
        """After sending to unknown agent, dead-letter list includes that message."""
        client.post(
            "/v1/relay/send",
            json={"to_agent": "agent_ghost_000", "channel": "direct", "payload": "lost msg"},
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        resp = client.get(
            "/v1/messages/dead-letter",
            headers={"X-API-Key": seed_agents["agent1"]["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any(m["to_agent"] == "agent_ghost_000" for m in data["messages"])

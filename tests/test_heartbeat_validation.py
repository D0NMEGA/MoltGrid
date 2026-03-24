"""
Phase 61 INF-03: Heartbeat status enum validation tests.

Verifies that POST /v1/heartbeat:
- Accepts valid statuses: online, busy, idle, offline
- Rejects invalid statuses with 422 and lists valid values
- Defaults to "online" when no status is provided
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest


VALID_STATUSES = ["online", "busy", "idle", "offline"]
INVALID_STATUSES = ["worker_running", "session_based", "active", "unknown", "ready", ""]


class TestHeartbeatValidStatus:
    """Valid status strings should return 200."""

    @pytest.mark.parametrize("status", VALID_STATUSES)
    def test_valid_status_returns_200(self, client, seed_agents, status):
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={"status": status},
            headers={"X-API-Key": agent["key"]},
        )
        assert resp.status_code == 200, f"status={status!r} should be accepted, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["status"] == status

    def test_default_status_is_online(self, client, seed_agents):
        """No status field should default to 'online' and return 200."""
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={},
            headers={"X-API-Key": agent["key"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "online"


class TestHeartbeatInvalidStatus:
    """Invalid status strings should return 422 with valid values listed."""

    @pytest.mark.parametrize("status", INVALID_STATUSES)
    def test_invalid_status_returns_422(self, client, seed_agents, status):
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={"status": status},
            headers={"X-API-Key": agent["key"]},
        )
        assert resp.status_code == 422, f"status={status!r} should be rejected with 422, got {resp.status_code}: {resp.text}"

    @pytest.mark.parametrize("status", INVALID_STATUSES)
    def test_invalid_status_lists_valid_values(self, client, seed_agents, status):
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={"status": status},
            headers={"X-API-Key": agent["key"]},
        )
        # Response may use custom error handler (details list) or standard FastAPI (detail)
        body = resp.json()
        # Serialize entire response body to check for valid values
        body_str = str(body).lower()
        for valid in VALID_STATUSES:
            assert valid in body_str, f"422 response should list '{valid}' as a valid option"

    def test_worker_running_rejected(self, client, seed_agents):
        """Specifically test that the old 'worker_running' value is rejected."""
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={"status": "worker_running"},
            headers={"X-API-Key": agent["key"]},
        )
        assert resp.status_code == 422

    def test_session_based_rejected(self, client, seed_agents):
        """Specifically test that the old 'session_based' value is rejected."""
        agent = seed_agents["agent1"]
        resp = client.post(
            "/v1/heartbeat",
            json={"status": "session_based"},
            headers={"X-API-Key": agent["key"]},
        )
        assert resp.status_code == 422

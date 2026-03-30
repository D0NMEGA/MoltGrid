"""
Tests for batch endpoints -- POST /v1/memory/batch and POST /v1/queue/batch.

Verifies:
- Batch memory stores items independently with per-item results
- Batch queue submits jobs independently with per-item job_ids
- Partial failures do not block successful items
- 100-item max enforced via Pydantic validation
- Auth required (X-API-Key)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["MOLTGRID_DB"] = "test_batch.db"
os.environ["TURNSTILE_SECRET_KEY"] = ""
os.environ["RATE_LIMIT_ENABLED"] = "false"

import uuid
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from main import app, init_db

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """Wipe and re-init the SQLite DB before every test."""
    db_path = str(tmp_path / "test_batch.db")
    monkeypatch.setenv("MOLTGRID_DB", db_path)
    import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setattr(db_module, "_sqlite_pool", None)
    init_db()


def _register_agent():
    """Register an agent and return (agent_id, api_key, headers)."""
    name = f"batch-test-agent-{uuid.uuid4().hex[:8]}"
    with patch("main._queue_email"):
        r = client.post("/v1/register", json={"name": name})
    assert r.status_code == 200, r.text
    data = r.json()
    return data["agent_id"], data["api_key"], {"X-API-Key": data["api_key"]}


class TestMemoryBatch:
    """POST /v1/memory/batch endpoint tests."""

    def test_batch_stores_multiple_items(self):
        """3 items all succeed, verify counts."""
        _, _, headers = _register_agent()
        items = [
            {"key": f"bk_{i}", "value": f"val_{i}"}
            for i in range(3)
        ]
        r = client.post("/v1/memory/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0
        assert len(data["results"]) == 3
        for res in data["results"]:
            assert res["success"] is True
            assert res["status"] == "stored"

    def test_batch_partial_failure(self):
        """1 item with invalid key + 1 valid item returns mixed results."""
        _, _, headers = _register_agent()
        items = [
            {"key": "invalid key with spaces!", "value": "v1"},
            {"key": "valid_key", "value": "v2"},
        ]
        r = client.post("/v1/memory/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        # First item failed
        assert data["results"][0]["success"] is False
        assert data["results"][0]["status"] == "error"
        assert data["results"][0]["error"] is not None
        # Second item succeeded
        assert data["results"][1]["success"] is True
        assert data["results"][1]["status"] == "stored"

    def test_batch_exceeds_limit(self):
        """101 items returns 422."""
        _, _, headers = _register_agent()
        items = [{"key": f"k{i}", "value": f"v{i}"} for i in range(101)]
        r = client.post("/v1/memory/batch", json={"items": items}, headers=headers)
        assert r.status_code == 422

    def test_batch_empty_items(self):
        """Empty items list returns 422."""
        _, _, headers = _register_agent()
        r = client.post("/v1/memory/batch", json={"items": []}, headers=headers)
        assert r.status_code == 422

    def test_batch_items_readable(self):
        """Store via batch, then GET /v1/memory/{key} to verify stored."""
        _, _, headers = _register_agent()
        items = [
            {"key": "readable_key", "value": "readable_value"},
        ]
        r = client.post("/v1/memory/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        # Now read it back
        r2 = client.get("/v1/memory/readable_key", headers=headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["value"] == "readable_value"

    def test_batch_requires_auth(self):
        """No X-API-Key returns 401 or 403."""
        r = client.post("/v1/memory/batch", json={"items": [{"key": "k", "value": "v"}]})
        assert r.status_code in (401, 403)


class TestQueueBatch:
    """POST /v1/queue/batch endpoint tests."""

    def test_batch_submits_multiple_jobs(self):
        """3 items with different queue_names/priorities all succeed."""
        _, _, headers = _register_agent()
        items = [
            {"payload": "job1"},
            {"payload": "job2", "queue_name": "fast", "priority": 5},
            {"payload": {"data": "structured"}, "queue_name": "slow", "priority": 1},
        ]
        r = client.post("/v1/queue/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 3
        assert data["succeeded"] == 3
        assert data["failed"] == 0
        assert len(data["results"]) == 3
        for res in data["results"]:
            assert res["success"] is True
            assert res["status"] == "pending"
            assert res["job_id"] is not None
            assert res["job_id"].startswith("job_")

    def test_batch_partial_failure_oversized(self):
        """1 oversized payload + 1 valid item returns mixed results."""
        _, _, headers = _register_agent()
        oversized = "x" * 200_000  # exceeds MAX_QUEUE_PAYLOAD_SIZE (100KB)
        items = [
            {"payload": oversized},
            {"payload": "small_job"},
        ]
        r = client.post("/v1/queue/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["total"] == 2
        assert data["succeeded"] == 1
        assert data["failed"] == 1
        assert data["results"][0]["success"] is False
        assert data["results"][0]["status"] == "error"
        assert data["results"][1]["success"] is True

    def test_batch_exceeds_limit(self):
        """101 items returns 422."""
        _, _, headers = _register_agent()
        items = [{"payload": f"job{i}"} for i in range(101)]
        r = client.post("/v1/queue/batch", json={"items": items}, headers=headers)
        assert r.status_code == 422

    def test_batch_empty_items(self):
        """Empty items list returns 422."""
        _, _, headers = _register_agent()
        r = client.post("/v1/queue/batch", json={"items": []}, headers=headers)
        assert r.status_code == 422

    def test_batch_jobs_retrievable(self):
        """Submit via batch, GET /v1/queue/{job_id} for each."""
        _, _, headers = _register_agent()
        items = [
            {"payload": "retrievable_job_1"},
            {"payload": "retrievable_job_2"},
        ]
        r = client.post("/v1/queue/batch", json={"items": items}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        for res in data["results"]:
            job_id = res["job_id"]
            r2 = client.get(f"/v1/queue/{job_id}", headers=headers)
            assert r2.status_code == 200, r2.text
            assert r2.json()["job_id"] == job_id
            assert r2.json()["status"] == "pending"

    def test_batch_requires_auth(self):
        """No X-API-Key returns 401 or 403."""
        r = client.post("/v1/queue/batch", json={"items": [{"payload": "test"}]})
        assert r.status_code in (401, 403)

"""
Phase 71 Plan 01 -- Marketplace claim race condition regression tests.

Tests for MKT-01: Atomic marketplace claim with rowcount verification.

Behaviors verified:
  Test 1: Single agent claims an open task -- gets 200 with status "claimed"
  Test 2: Two sequential claims on same task -- first gets 200, second gets 409
  Test 3: Agent claims a task that does not exist -- gets 404
  Test 4: Agent tries to claim own task -- gets 400
  Test 5: Race condition simulation -- rowcount=0 on second call produces 409
"""
import sys
import os
import json
import uuid
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db as _db_module
from db import _init_db_sqlite
from helpers import hash_key


# ---- Fixtures ----------------------------------------------------------------

@pytest.fixture
def test_db(tmp_path):
    """Create a fresh SQLite DB with full schema."""
    db_path = str(tmp_path / "test_marketplace_race.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _init_db_sqlite(conn)
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def seed_agents(test_db):
    """Seed two test agents and return their IDs + API keys."""
    conn = sqlite3.connect(test_db)
    conn.row_factory = sqlite3.Row
    now = datetime.now(timezone.utc).isoformat()
    agent1_id = f"agent_{uuid.uuid4().hex[:16]}"
    agent1_key = f"mg_{uuid.uuid4().hex}"
    agent2_id = f"agent_{uuid.uuid4().hex[:16]}"
    agent2_key = f"mg_{uuid.uuid4().hex}"
    for aid, akey in [(agent1_id, agent1_key), (agent2_id, agent2_key)]:
        conn.execute(
            "INSERT INTO agents (agent_id, api_key_hash, name, created_at, owner_id, credits) VALUES (?,?,?,?,?,?)",
            (aid, hash_key(akey), f"Test-{aid[:8]}", now, "test_user", 100),
        )
    conn.commit()
    conn.close()
    return {
        "db_path": test_db,
        "agent1": {"id": agent1_id, "key": agent1_key},
        "agent2": {"id": agent2_id, "key": agent2_key},
    }


@pytest.fixture
def client(seed_agents):
    """TestClient that uses the isolated test DB."""
    db_path = seed_agents["db_path"]
    with patch.object(_db_module, "DB_PATH", db_path), \
         patch.object(_db_module, "_sqlite_pool", None), \
         patch.object(_db_module, "DB_BACKEND", "sqlite"):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _create_task(client, creator_key: str, title: str = "Test Task", reward: int = 10) -> str:
    """Helper: create a marketplace task and return its task_id."""
    resp = client.post(
        "/v1/marketplace/tasks",
        json={"title": title, "category": "testing", "reward_credits": reward},
        headers={"X-API-Key": creator_key},
    )
    assert resp.status_code == 200, f"Task creation failed: {resp.text}"
    return resp.json()["task_id"]


# ---- Tests -------------------------------------------------------------------

def test_single_claim_succeeds(client, seed_agents):
    """Test 1: Single agent claims an open task -- gets 200 with status 'claimed'."""
    agent1 = seed_agents["agent1"]
    agent2 = seed_agents["agent2"]

    task_id = _create_task(client, agent1["key"])

    resp = client.post(
        f"/v1/marketplace/tasks/{task_id}/claim",
        headers={"X-API-Key": agent2["key"]},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["status"] == "claimed"
    assert data["task_id"] == task_id
    assert data["claimed_by"] == agent2["id"]


def test_sequential_claims_second_gets_409(client, seed_agents):
    """Test 2: Two sequential claims on same task -- first gets 200, second gets 409."""
    agent1 = seed_agents["agent1"]
    agent2 = seed_agents["agent2"]

    # agent1 creates the task
    task_id = _create_task(client, agent1["key"], title="Sequential Claim Task")

    # agent2 claims it first -- should succeed
    resp1 = client.post(
        f"/v1/marketplace/tasks/{task_id}/claim",
        headers={"X-API-Key": agent2["key"]},
    )
    assert resp1.status_code == 200, f"First claim should succeed: {resp1.text}"

    # agent2 tries to claim again -- already claimed, should 409
    resp2 = client.post(
        f"/v1/marketplace/tasks/{task_id}/claim",
        headers={"X-API-Key": agent2["key"]},
    )
    assert resp2.status_code == 409, f"Second claim should be 409, got {resp2.status_code}: {resp2.text}"


def test_claim_nonexistent_task_returns_404(client, seed_agents):
    """Test 3: Agent claims a task that does not exist -- gets 404."""
    agent2 = seed_agents["agent2"]

    resp = client.post(
        "/v1/marketplace/tasks/nonexistent_task_id/claim",
        headers={"X-API-Key": agent2["key"]},
    )
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}: {resp.text}"


def test_claim_own_task_returns_400(client, seed_agents):
    """Test 4: Agent tries to claim their own task -- gets 400."""
    agent1 = seed_agents["agent1"]

    task_id = _create_task(client, agent1["key"], title="Own Task")

    resp = client.post(
        f"/v1/marketplace/tasks/{task_id}/claim",
        headers={"X-API-Key": agent1["key"]},
    )
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}: {resp.text}"


def test_race_condition_rowcount_zero_returns_409(client, seed_agents):
    """Test 5: Simulate race -- rowcount=0 after UPDATE means another agent won; verify 409.

    This directly tests the rowcount check by patching the db.execute UPDATE
    to return a mock result with rowcount=0, simulating the case where another
    agent claimed the task between the SELECT and the UPDATE.
    """
    agent1 = seed_agents["agent1"]
    agent2 = seed_agents["agent2"]

    task_id = _create_task(client, agent1["key"], title="Race Condition Task")

    from contextlib import contextmanager

    db_path = seed_agents["db_path"]
    call_tracker = {"update_calls": 0}

    class RowcountZeroCursor:
        """Wraps a real sqlite3.Cursor but reports rowcount=0."""
        def __init__(self, real_cursor):
            self._cursor = real_cursor
            self.rowcount = 0

        def fetchone(self):
            return self._cursor.fetchone()

        def fetchall(self):
            return self._cursor.fetchall()

        def __iter__(self):
            return iter(self._cursor)

    class InterceptingConnection:
        """Wraps sqlite3.Connection to intercept specific UPDATE and return rowcount=0."""
        def __init__(self, conn):
            self._conn = conn
            self.row_factory = conn.row_factory

        def execute(self, sql, params=()):
            result = self._conn.execute(sql, params)
            if "UPDATE marketplace SET status='claimed'" in sql:
                call_tracker["update_calls"] += 1
                # Return a cursor that reports rowcount=0 (simulating lost race)
                return RowcountZeroCursor(result)
            return result

        def commit(self):
            self._conn.commit()

        def rollback(self):
            self._conn.rollback()

        def close(self):
            self._conn.close()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type:
                self._conn.rollback()
            else:
                self._conn.commit()
            self._conn.close()

    @contextmanager
    def patched_get_db():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        wrapped = InterceptingConnection(conn)
        try:
            yield wrapped
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    with patch("routers.marketplace.get_db", patched_get_db):
        resp = client.post(
            f"/v1/marketplace/tasks/{task_id}/claim",
            headers={"X-API-Key": agent2["key"]},
        )

    assert resp.status_code == 409, (
        f"Expected 409 when rowcount=0 (race lost), got {resp.status_code}: {resp.text}"
    )
    assert call_tracker["update_calls"] > 0, "UPDATE was not called -- test setup issue"

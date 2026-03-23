"""
Shared pytest fixtures for Phase 42 relay tests.
Uses an isolated SQLite DB per test via MOLTGRID_DB env override.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import db as _db_module
from db import _init_db_sqlite
from helpers import hash_key


@pytest.fixture
def test_db(tmp_path):
    """Create a fresh SQLite DB with full schema in a temp directory."""
    db_path = str(tmp_path / "test.db")
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
            "INSERT INTO agents (agent_id, api_key_hash, name, created_at, owner_id) VALUES (?,?,?,?,?)",
            (aid, hash_key(akey), f"Test-{aid[:8]}", now, "test_user"),
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
    """TestClient that uses the isolated test DB.

    Patches DB_PATH at module level and disables the SQLite pool so
    get_db() falls back to the direct-connect path using the test DB.
    """
    db_path = seed_agents["db_path"]

    with patch.object(_db_module, "DB_PATH", db_path), \
         patch.object(_db_module, "_sqlite_pool", None):
        from main import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

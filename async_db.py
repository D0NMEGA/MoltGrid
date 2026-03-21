"""
MoltGrid Async Database Helpers.

Uses native asyncpg connection pool for PostgreSQL when available (zero
thread overhead). Falls back to asyncio.to_thread() wrapping sync get_db()
for SQLite local dev when _asyncpg_pool is None.

Usage:
    rows = await async_db_fetchall("SELECT * FROM agents WHERE public=1 LIMIT ?", (50,))
    row  = await async_db_fetchone("SELECT COUNT(*) as c FROM memory", ())
    await async_db_execute("UPDATE agents SET heartbeat_at=? WHERE agent_id=?", (now, aid))
    row  = await async_db_execute_returning("INSERT INTO t (a) VALUES (?) RETURNING *", ("v",))
"""

import asyncio
import logging
from typing import Any, Optional, Sequence

from db import get_db, _asyncpg_pool, _translate_sql_asyncpg

logger = logging.getLogger("moltgrid.async_db")


# ─── Sync helpers (SQLite fallback path) ─────────────────────────────────────

def _sync_fetchall(query: str, params: Optional[Sequence[Any]] = None) -> list[dict]:
    """Run a query synchronously and return all rows as dicts."""
    with get_db() as db:
        if params:
            rows = db.execute(query, params).fetchall()
        else:
            rows = db.execute(query).fetchall()
        return [dict(r) for r in rows]


def _sync_fetchone(query: str, params: Optional[Sequence[Any]] = None) -> Optional[dict]:
    """Run a query synchronously and return one row as dict (or None)."""
    with get_db() as db:
        if params:
            row = db.execute(query, params).fetchone()
        else:
            row = db.execute(query).fetchone()
        return dict(row) if row else None


def _sync_execute(query: str, params: Optional[Sequence[Any]] = None) -> None:
    """Run a write query synchronously (INSERT/UPDATE/DELETE)."""
    with get_db() as db:
        if params:
            db.execute(query, params)
        else:
            db.execute(query)


# ─── Helper: resolve pool at call time ────────────────────────────────────────

def _get_asyncpg_pool():
    """Return the current asyncpg pool from db module (resolved at call time).

    We import _asyncpg_pool at module level for convenience, but the global
    variable in db.py is mutated after import (during lifespan startup).
    This function reads the live value from db module directly.
    """
    import db as _db_mod
    return _db_mod._asyncpg_pool


# ─── Native async functions ──────────────────────────────────────────────────

async def async_db_fetchall(query: str, params: Optional[Sequence[Any]] = None) -> list[dict]:
    """Execute a query and return all rows as dicts.

    Uses asyncpg pool.fetch() when available (postgres path).
    Falls back to asyncio.to_thread for SQLite.
    """
    pool = _get_asyncpg_pool()
    if pool is not None:
        translated = _translate_sql_asyncpg(query)
        args = tuple(params) if params else ()
        rows = await pool.fetch(translated, *args)
        return [dict(r) for r in rows]
    return await asyncio.to_thread(_sync_fetchall, query, params)


async def async_db_fetchone(query: str, params: Optional[Sequence[Any]] = None) -> Optional[dict]:
    """Execute a query and return one row as dict (or None).

    Uses asyncpg pool.fetchrow() when available (postgres path).
    Falls back to asyncio.to_thread for SQLite.
    """
    pool = _get_asyncpg_pool()
    if pool is not None:
        translated = _translate_sql_asyncpg(query)
        args = tuple(params) if params else ()
        row = await pool.fetchrow(translated, *args)
        return dict(row) if row else None
    return await asyncio.to_thread(_sync_fetchone, query, params)


async def async_db_execute(query: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute a write query (INSERT/UPDATE/DELETE).

    Uses asyncpg pool.execute() when available (postgres path).
    Falls back to asyncio.to_thread for SQLite.
    """
    pool = _get_asyncpg_pool()
    if pool is not None:
        translated = _translate_sql_asyncpg(query)
        args = tuple(params) if params else ()
        await pool.execute(translated, *args)
        return
    await asyncio.to_thread(_sync_execute, query, params)


async def async_db_execute_returning(
    query: str, params: Optional[Sequence[Any]] = None
) -> Optional[dict]:
    """Execute an INSERT...RETURNING query and return the resulting row.

    Uses asyncpg pool.fetchrow() when available (postgres path).
    Falls back to asyncio.to_thread with _sync_fetchone for SQLite.
    """
    pool = _get_asyncpg_pool()
    if pool is not None:
        translated = _translate_sql_asyncpg(query)
        args = tuple(params) if params else ()
        row = await pool.fetchrow(translated, *args)
        return dict(row) if row else None
    return await asyncio.to_thread(_sync_fetchone, query, params)

"""
Tests for async_db.py native asyncpg pool integration.

TDD RED phase: Verify async_db functions use asyncpg pool when available,
fall back to thread-wrapped sync when pool is None.
"""

import os
import sys
import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestAsyncDbFetchallAsyncpg:
    """Test async_db_fetchall uses asyncpg pool when available."""

    @pytest.mark.asyncio
    async def test_uses_asyncpg_pool_fetch(self):
        """async_db_fetchall calls pool.fetch() when _asyncpg_pool is not None."""
        import async_db
        import db

        mock_record1 = {"id": 1, "name": "alice"}
        mock_record2 = {"id": 2, "name": "bob"}
        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[mock_record1, mock_record2])

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            result = await async_db.async_db_fetchall("SELECT * FROM t WHERE a=?", (1,))
            mock_pool.fetch.assert_called_once()
            assert isinstance(result, list)
            assert len(result) == 2
        finally:
            db._asyncpg_pool = old_pool

    @pytest.mark.asyncio
    async def test_sql_is_translated(self):
        """SQL is translated via _translate_sql_asyncpg before execution."""
        import async_db
        import db

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[])

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            await async_db.async_db_fetchall("SELECT * FROM t WHERE a=? AND b=?", (1, 2))
            call_args = mock_pool.fetch.call_args
            sql_arg = call_args[0][0]
            assert "$1" in sql_arg
            assert "$2" in sql_arg
            assert "?" not in sql_arg
        finally:
            db._asyncpg_pool = old_pool

    @pytest.mark.asyncio
    async def test_fallback_to_thread_when_pool_none(self):
        """Falls back to asyncio.to_thread when _asyncpg_pool is None."""
        import async_db
        import db

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = None
            with patch("async_db.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = [{"id": 1}]
                result = await async_db.async_db_fetchall("SELECT 1", ())
                mock_thread.assert_called_once()
        finally:
            db._asyncpg_pool = old_pool


class TestAsyncDbFetchoneAsyncpg:
    """Test async_db_fetchone uses asyncpg pool when available."""

    @pytest.mark.asyncio
    async def test_uses_asyncpg_pool_fetchrow(self):
        """async_db_fetchone calls pool.fetchrow() when _asyncpg_pool is not None."""
        import async_db
        import db

        mock_record = {"id": 1, "name": "alice"}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=mock_record)

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            result = await async_db.async_db_fetchone("SELECT * FROM t WHERE id=?", (1,))
            mock_pool.fetchrow.assert_called_once()
            assert result is not None
            assert result["id"] == 1
        finally:
            db._asyncpg_pool = old_pool

    @pytest.mark.asyncio
    async def test_returns_none_when_no_row(self):
        """async_db_fetchone returns None when fetchrow returns None."""
        import async_db
        import db

        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=None)

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            result = await async_db.async_db_fetchone("SELECT * FROM t WHERE id=?", (999,))
            assert result is None
        finally:
            db._asyncpg_pool = old_pool


class TestAsyncDbExecuteAsyncpg:
    """Test async_db_execute uses asyncpg pool when available."""

    @pytest.mark.asyncio
    async def test_uses_asyncpg_pool_execute(self):
        """async_db_execute calls pool.execute() when _asyncpg_pool is not None."""
        import async_db
        import db

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="INSERT 0 1")

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            await async_db.async_db_execute("INSERT INTO t (a) VALUES (?)", ("val",))
            mock_pool.execute.assert_called_once()
        finally:
            db._asyncpg_pool = old_pool

    @pytest.mark.asyncio
    async def test_sql_translated_for_execute(self):
        """SQL is translated via _translate_sql_asyncpg for execute calls."""
        import async_db
        import db

        mock_pool = AsyncMock()
        mock_pool.execute = AsyncMock(return_value="UPDATE 1")

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            await async_db.async_db_execute("UPDATE t SET a=? WHERE b=?", ("x", "y"))
            call_args = mock_pool.execute.call_args
            sql_arg = call_args[0][0]
            assert "$1" in sql_arg
            assert "$2" in sql_arg
            assert "?" not in sql_arg
        finally:
            db._asyncpg_pool = old_pool


class TestAsyncDbResultFormat:
    """Test that results are returned as list[dict] / Optional[dict]."""

    @pytest.mark.asyncio
    async def test_fetchall_returns_list_of_dicts(self):
        """Results from asyncpg pool are converted to list[dict]."""
        import async_db
        import db

        # asyncpg.Record supports dict() conversion
        mock_record = MagicMock()
        mock_record.__iter__ = MagicMock(return_value=iter([("id", 1), ("name", "test")]))
        mock_record.items = MagicMock(return_value=[("id", 1), ("name", "test")])

        mock_pool = AsyncMock()
        mock_pool.fetch = AsyncMock(return_value=[{"id": 1, "name": "test"}])

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            result = await async_db.async_db_fetchall("SELECT * FROM t", ())
            assert isinstance(result, list)
            for row in result:
                assert isinstance(row, dict)
        finally:
            db._asyncpg_pool = old_pool


class TestAsyncDbExecuteReturning:
    """Test async_db_execute_returning for INSERT...RETURNING patterns."""

    @pytest.mark.asyncio
    async def test_execute_returning_uses_fetchrow(self):
        """async_db_execute_returning returns a row from INSERT...RETURNING."""
        import async_db
        import db

        mock_record = {"id": 1, "created_at": "2026-01-01"}
        mock_pool = AsyncMock()
        mock_pool.fetchrow = AsyncMock(return_value=mock_record)

        old_pool = db._asyncpg_pool
        try:
            db._asyncpg_pool = mock_pool
            result = await async_db.async_db_execute_returning(
                "INSERT INTO t (a) VALUES (?) RETURNING *", ("val",)
            )
            mock_pool.fetchrow.assert_called_once()
            assert result is not None
            assert result["id"] == 1
        finally:
            db._asyncpg_pool = old_pool

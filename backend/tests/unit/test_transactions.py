"""
Unit tests for app/utils/transactions.py

Uses a mock AsyncSession to test transaction context manager behavior.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.utils.transactions import transaction, with_transaction


def _make_db(in_transaction: bool = False) -> AsyncMock:
    """Build an AsyncMock session where in_transaction() is synchronous."""
    db = AsyncMock()
    # in_transaction is a plain synchronous method on SQLAlchemy sessions
    db.in_transaction = MagicMock(return_value=in_transaction)
    return db


class TestTransactionContextManager:
    async def test_commits_when_no_exception(self):
        db = _make_db(in_transaction=False)

        async with transaction(db):
            pass

        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()

    async def test_rollback_on_exception(self):
        db = _make_db(in_transaction=False)

        with pytest.raises(ValueError):
            async with transaction(db):
                raise ValueError("boom")

        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()

    async def test_yields_db_session(self):
        db = _make_db(in_transaction=False)

        async with transaction(db) as session:
            assert session is db

    async def test_already_in_transaction_skips_commit(self):
        db = _make_db(in_transaction=True)

        async with transaction(db):
            pass

        db.commit.assert_not_awaited()
        db.rollback.assert_not_awaited()

    async def test_already_in_transaction_yields_db(self):
        db = _make_db(in_transaction=True)

        async with transaction(db) as session:
            assert session is db

    async def test_savepoint_uses_begin_nested(self):
        db = _make_db()
        # Mock begin_nested as an async context manager
        nested_cm = AsyncMock()
        nested_cm.__aenter__ = AsyncMock(return_value=None)
        nested_cm.__aexit__ = AsyncMock(return_value=False)
        db.begin_nested = MagicMock(return_value=nested_cm)

        async with transaction(db, savepoint=True):
            pass

        db.begin_nested.assert_called_once()

    async def test_exception_is_reraised_after_rollback(self):
        db = _make_db(in_transaction=False)

        class CustomError(Exception):
            pass

        with pytest.raises(CustomError):
            async with transaction(db):
                raise CustomError("test error")

        db.rollback.assert_awaited_once()

    async def test_multiple_operations_in_transaction(self):
        db = _make_db(in_transaction=False)
        results = []

        async with transaction(db):
            results.append(1)
            results.append(2)

        assert results == [1, 2]
        db.commit.assert_awaited_once()


class TestWithTransaction:
    async def test_with_transaction_calls_func_and_commits(self):
        db = _make_db(in_transaction=False)

        async def my_func(session, x, y):
            return x + y

        result = await with_transaction(db, my_func, 3, 4)

        assert result == 7
        db.commit.assert_awaited_once()

    async def test_with_transaction_passes_kwargs(self):
        db = _make_db(in_transaction=False)

        async def my_func(session, name="default"):
            return name

        result = await with_transaction(db, my_func, name="custom")
        assert result == "custom"

    async def test_with_transaction_rollback_on_error(self):
        db = _make_db(in_transaction=False)

        async def failing_func(session):
            raise RuntimeError("db error")

        with pytest.raises(RuntimeError):
            await with_transaction(db, failing_func)

        db.rollback.assert_awaited_once()

    async def test_with_transaction_returns_none_func_result(self):
        db = _make_db(in_transaction=False)

        async def no_return_func(session):
            pass

        result = await with_transaction(db, no_return_func)
        assert result is None

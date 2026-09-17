"""
DB-level immutability check for agent_audit_logs.

This can't be exercised against the SQLite in-memory test_db fixture (SQLite
has no PL/pgSQL triggers), so it talks to the real dev Postgres directly via
settings.database_url and applies migrations first. Skips cleanly if that
Postgres isn't reachable, rather than failing the whole suite.
"""
import pytest
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings


async def _migrated_engine():
    """Real Postgres engine with migrations applied through head (013+)."""
    import alembic.config

    alembic_cfg = alembic.config.Config("alembic.ini")
    # alembic's command API is sync; run it in a thread so it doesn't block
    # the event loop this test itself is running on.
    import asyncio
    import functools

    from alembic import command

    await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(command.upgrade, alembic_cfg, "head")
    )
    return create_async_engine(settings.database_url)


@pytest.fixture
async def real_pg_engine():
    try:
        engine = await _migrated_engine()
        async with engine.connect():
            pass  # confirms the DB is actually reachable
    except Exception as exc:
        pytest.skip(f"real Postgres unreachable — skipping DB-trigger test ({exc})")
    yield engine
    await engine.dispose()


class TestAuditLogImmutability:
    async def test_update_on_agent_audit_logs_is_rejected(self, real_pg_engine):
        async with real_pg_engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO agent_audit_logs (id, event_type, actor, outcome, details, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'action_approved', 'system', 'success', '{}', now(), now())"
            )

        with pytest.raises(DBAPIError, match="append-only"):
            async with real_pg_engine.begin() as conn:
                await conn.exec_driver_sql(
                    "UPDATE agent_audit_logs SET outcome = 'failure' WHERE actor = 'system'"
                )

    async def test_delete_on_agent_audit_logs_still_works(self, real_pg_engine):
        """The trigger must only block UPDATE — the retention sweep depends on DELETE."""
        async with real_pg_engine.begin() as conn:
            await conn.exec_driver_sql(
                "INSERT INTO agent_audit_logs (id, event_type, actor, outcome, details, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'action_approved', 'delete-me', 'success', '{}', now(), now())"
            )
            result = await conn.exec_driver_sql(
                "DELETE FROM agent_audit_logs WHERE actor = 'delete-me'"
            )
            assert result.rowcount == 1

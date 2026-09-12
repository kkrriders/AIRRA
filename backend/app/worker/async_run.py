"""Run a coroutine from a sync Celery task without tripping over stale async clients.

Celery workers are synchronous processes, so each task body calls
``asyncio.run(...)`` — which creates a fresh event loop and closes it when the
coroutine returns. AIRRA's async clients are module-level singletons:

* ``app.services.prometheus_client._prometheus_client`` — an ``httpx.AsyncClient``
* ``app.core.redis._pool`` — a ``redis.asyncio`` connection pool

Both bind to the event loop that first created them. On the *second* task the
loop is gone, and the next call raises ``RuntimeError: Event loop is closed`` or
``... is bound to a different event loop``.

A fourth singleton hits the same failure mode more subtly:
``app.services.anomaly_monitor._monitor`` holds an ``asyncio.Semaphore`` that
throttles concurrent Prometheus queries. A semaphore only binds to a loop the
first time a caller actually has to *wait* (permits exhausted) — with the
default 5-service demo list and ``MAX_CONCURRENT_QUERIES = 5`` nobody ever
waits, so the bug was invisible. Configure 6+ monitored services and one
service per cycle must wait; it binds the semaphore to whichever loop is
running on the *first* cycle, then every later cycle (a new loop) raises
"bound to a different event loop" — inside ``async with``, before
``_check_service``'s own try/except, so ``asyncio.gather(...,
return_exceptions=True)`` swallows it with no log line at all. Net effect:
the last service in the monitored list gets checked exactly once, ever.

``run_async`` drops those singleton references before ``asyncio.run`` so the
next ``get_*()`` rebuilds them on the loop that is about to run.
"""
from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

_T = TypeVar("_T")


def run_async(coro: Coroutine[Any, Any, _T]) -> _T:
    """Reset loop-bound async state, then ``asyncio.run(coro)``.

    Three things outlive a single ``asyncio.run`` and break on the next one:

    * the httpx Prometheus client singleton  -> drop the reference
    * the redis.asyncio pool singleton        -> drop the reference
    * the SQLAlchemy async engine's connection pool, whose connections and their
      internal Futures are bound to the loop that opened them -> ``dispose()`` it
      from *inside* the new loop so the pool rebuilds cleanly. This is what fixed
      "got Future ... attached to a different loop" when the monitor tried to
      write an incident.
    """
    import app.core.redis as _redis
    import app.services.anomaly_monitor as _monitor
    import app.services.prometheus_client as _prom

    # ponytail: abandon-and-GC rather than aclose() — we are between event loops
    # and cannot await a clean shutdown here. That orphans ~1 httpx client per
    # task (once/min under Beat); GC plus TCP keepalive reap the sockets. If the
    # worker's task rate grows, move it to a persistent event loop instead.
    _prom._prometheus_client = None
    _redis._pool = None
    # Drop the AnomalyMonitor singleton too: its query semaphore lazily binds
    # to whichever loop first has to wait on it, which breaks the same way as
    # the two clients above once there are more monitored services than
    # MAX_CONCURRENT_QUERIES. Cheap to rebuild (no I/O in __init__); only cost
    # is losing the in-memory dedup fallback, which is Redis's backup anyway.
    _monitor._monitor = None

    async def _with_fresh_engine_pool() -> _T:
        from app.database import engine

        await engine.dispose()  # drop connections pooled on a now-dead loop
        try:
            return await coro
        finally:
            # dispose again before this loop closes so nothing is left pooled on
            # a loop the next task can't use (also silences a GC-time
            # "Event loop is closed" from asyncpg cleanup at interpreter exit).
            await engine.dispose()

    return asyncio.run(_with_fresh_engine_pool())


if __name__ == "__main__":
    # Self-check: two back-to-back run_async calls must each succeed, including a
    # real DB round-trip. Pre-fix, the second call raised "Event loop is closed"
    # (client singletons) or "Future attached to a different loop" (engine pool).
    from sqlalchemy import text

    import app.services.anomaly_monitor as _am
    import app.services.prometheus_client as _pc
    from app.database import get_db_context

    async def _touch() -> int:
        assert _pc.get_prometheus_client().client is not None
        async with get_db_context() as db:
            assert (await db.execute(text("SELECT 1"))).scalar() == 1
        return 1

    async def _exhaust_semaphore() -> int:
        # Force every permit to be taken so the next acquire in this call has to
        # actually wait — that's the only path that binds the semaphore's loop.
        mon = _am.get_monitor()
        n = mon.MAX_CONCURRENT_QUERIES

        async def _hold_and_release():
            async with mon._query_semaphore:
                await asyncio.sleep(0)

        await asyncio.gather(*(_hold_and_release() for _ in range(n + 1)))
        return 1

    assert run_async(_touch()) == 1
    assert run_async(_touch()) == 1  # would raise pre-fix
    assert run_async(_exhaust_semaphore()) == 1
    assert run_async(_exhaust_semaphore()) == 1  # would raise pre-fix (stale loop)
    print("async_run self-check OK")


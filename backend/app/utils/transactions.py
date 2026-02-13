"""
Database Transaction Utilities

Provides explicit transaction management with rollback support
for complex database operations involving multiple tables.

IMPORTANT - Usage with FastAPI:
- FastAPI's get_db() dependency does NOT auto-commit by default
- Endpoints are responsible for calling commit() explicitly
- This utility IS SAFE to use with FastAPI sessions
- Use this when you need atomic multi-table operations

When to use:
✅ Multi-table operations that must be atomic (create incident + hypotheses)
✅ Complex updates that should rollback together
✅ Nested transactions with savepoints

When NOT to use:
❌ Single insert/update operations (just call db.commit())
❌ Read-only operations (no transaction needed)
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


@asynccontextmanager
async def transaction(db: AsyncSession, savepoint: bool = False) -> AsyncGenerator[AsyncSession, None]:
    """
    Explicit transaction context manager with automatic rollback on errors.

    Safe to use with FastAPI's get_db() dependency - checks if transaction
    is already active and handles accordingly.

    Usage:
        async with transaction(db):
            # Multiple database operations
            db.add(obj1)
            db.add(obj2)
            # Automatically commits if no exception
            # Automatically rolls back if exception occurs

    Args:
        db: Database session
        savepoint: If True, uses a savepoint (nested transaction)

    Yields:
        Database session

    Example:
        # In a FastAPI endpoint:
        @app.post("/complex-operation")
        async def complex_op(db: AsyncSession = Depends(get_db)):
            async with transaction(db):
                incident = Incident(...)
                db.add(incident)
                await db.flush()  # Get incident.id

                hypothesis = Hypothesis(incident_id=incident.id, ...)
                db.add(hypothesis)
                # Commit happens automatically

    Note:
        If a transaction is already active (nested call), uses savepoint
        to avoid double-commit issues.
    """
    if savepoint:
        # Use savepoint for nested transactions
        async with db.begin_nested():
            yield db
    else:
        # Check if transaction is already active
        if db.in_transaction():
            # Already in a transaction, just yield (caller will commit)
            logger.debug("Transaction already active, using existing transaction")
            yield db
        else:
            # Start new transaction
            try:
                yield db
                await db.commit()
                logger.debug("Transaction committed successfully")
            except Exception as e:
                await db.rollback()
                logger.error(f"Transaction rolled back due to error: {e}", exc_info=True)
                raise


async def with_transaction(db: AsyncSession, func, *args, **kwargs):
    """
    Execute a function within a transaction.

    Usage:
        result = await with_transaction(db, my_function, arg1, arg2)

    Args:
        db: Database session
        func: Async function to execute
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of func
    """
    async with transaction(db):
        return await func(db, *args, **kwargs)

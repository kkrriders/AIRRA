"""
Database connection and session management.

Senior Engineering Note:
- Async sessions for non-blocking I/O
- Connection pooling configured
- Dependency injection pattern for FastAPI
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings

# Create async engine
engine: AsyncEngine = create_async_engine(
    str(settings.database_url),
    echo=settings.database_echo,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_pre_ping=True,  # Verify connections before using
    pool_recycle=3600,  # Recycle connections after 1 hour
)

# Create session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Endpoints are responsible for calling commit() explicitly,
    which keeps transaction boundaries clear and avoids double-commits.
    Rollback is handled automatically on unhandled exceptions.

    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions outside of FastAPI.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(select(Incident))
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database (create all tables).

    Use Alembic for migrations in production.
    This is useful for development and testing.
    """
    from app.models import Base
    # Import all models to register them with SQLAlchemy metadata
    from app.models.incident import Incident  # noqa: F401
    from app.models.hypothesis import Hypothesis  # noqa: F401
    from app.models.action import Action  # noqa: F401
    from app.models.engineer import Engineer  # noqa: F401
    from app.models.engineer_review import EngineerReview  # noqa: F401
    from app.models.incident_pattern import IncidentPattern  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections on shutdown."""
    await engine.dispose()

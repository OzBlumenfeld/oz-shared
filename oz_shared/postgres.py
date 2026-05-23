from collections.abc import AsyncGenerator, Callable
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(database_url: str, **kwargs: Any) -> AsyncEngine:
    return create_async_engine(database_url, **kwargs)


def make_session_factory(
    engine: AsyncEngine, **kwargs: Any
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, **kwargs)


def make_get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    async def get_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    return get_session

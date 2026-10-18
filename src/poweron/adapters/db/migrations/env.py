import asyncio
import os
from typing import Any, Literal

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from poweron.adapters.db.tables import UtcDateTime, metadata

DEFAULT_URL = "sqlite+aiosqlite:///./data/poweron.sqlite3"


def database_url() -> str:
    url = context.config.get_main_option("sqlalchemy.url")
    return url or os.environ.get("DATABASE_URL", DEFAULT_URL)


def render_item(kind: str, item: Any, _context: Any) -> str | Literal[False]:
    if kind == "type" and isinstance(item, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


OPTIONS: dict[str, Any] = {
    "target_metadata": metadata,
    "render_as_batch": True,
    "render_item": render_item,
}


def run_with(connection: Connection) -> None:
    context.configure(connection=connection, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(database_url())
    async with engine.connect() as connection:
        await connection.run_sync(run_with)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=database_url(), **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_online())

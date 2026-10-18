import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import text

from poweron.adapters.db.repository import (
    SqlRepository,
    alembic_config,
    create_engine,
    run_migrations,
)
from poweron.adapters.db.tables import UtcDateTime


def test_migrations_match_the_tables(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'check.sqlite3'}"
    run_migrations(url)
    command.check(alembic_config(url))


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        UtcDateTime().process_bind_param(datetime(2026, 10, 17), dialect=None)  # type: ignore[arg-type]


async def test_migration_keeps_the_queue_of_an_existing_subscription(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'upgrade.sqlite3'}"
    config = alembic_config(url)
    await asyncio.to_thread(command.upgrade, config, "80be0edcac6d")
    engine = create_engine(url)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO users (id, created_at, timezone, locale) VALUES (1, '2026-10-17', 'Europe/Kyiv', 'uk')"
            )
        )
        await connection.execute(
            text(
                "INSERT INTO subscriptions (id, user_id, label, city_id, city_name, street_id, "
                "street_name, building_id, building_name, cherg_gpv, notify_on_update, "
                "remind_before_off_min, remind_before_on_min, created_at) "
                "VALUES (1, 1, 'Дім', 1, 'Тернопіль', 2, 'Руська', 3, '5', '4.1', 1, 30, 0, '2026-10-17')"
            )
        )
    await engine.dispose()

    await asyncio.to_thread(command.upgrade, config, "head")

    repository = SqlRepository(create_engine(url))
    [subscription] = await repository.all_subscriptions()
    assert subscription.subqueues == ("4.1",)
    assert subscription.tracked_subqueues == ("4.1",)

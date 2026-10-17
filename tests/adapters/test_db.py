from datetime import datetime
from pathlib import Path

import pytest
from alembic import command

from poweron.adapters.db.repository import alembic_config, run_migrations
from poweron.adapters.db.tables import UtcDateTime


def test_migrations_match_the_tables(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'check.sqlite3'}"
    run_migrations(url)
    command.check(alembic_config(url))


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError):
        UtcDateTime().process_bind_param(datetime(2026, 10, 17), dialect=None)  # type: ignore[arg-type]

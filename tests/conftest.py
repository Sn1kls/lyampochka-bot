import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from poweron.adapters.db.repository import SqlRepository, create_engine, run_migrations

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.sqlite3'}"
    run_migrations(url)
    return url


@pytest.fixture
async def repository(database_url: str) -> AsyncIterator[SqlRepository]:
    engine = create_engine(database_url)
    yield SqlRepository(engine)
    await engine.dispose()

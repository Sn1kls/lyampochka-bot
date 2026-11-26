import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from poweron.adapters.db.repository import create_engine
from poweron.adapters.db.voe_catalog import CatalogRow, VoeCatalog, stable_id
from poweron.adapters.db.voe_outages import (
    MAX_AGE,
    OutageRow,
    OutagesImportRefused,
    VoeOutages,
    parse_snapshot,
)
from poweron.core.domain.models import PlannedWork

NOW = datetime(2026, 11, 26, 10, 0, tzinfo=UTC)  # 12:00 in Kyiv
CITY = stable_id("Луцький", "Ківерці")
STREET = stable_id("Луцький", "Ківерці", "Європейська")
EMERGENCY = [
    "Луцький",
    "Ківерці",
    "Європейська",
    ["1", "1А"],
    "emergency",
    "2026-11-26 10:37",
    "2026-11-26 17:00",
    "Аварійний випадок в мережах",
]
PLANNED = [
    "Луцький",
    "Ківерці",
    "Європейська",
    ["3"],
    "planned",
    "2026-11-26 09:00",
    "2026-11-26 16:00",
    "Планові ремонтні роботи",
]


def snapshot(*rows: list[Any]) -> bytes:
    return json.dumps({"rows": list(rows)}, ensure_ascii=False).encode()


def parsed(*rows: list[Any]) -> list[OutageRow]:
    found, skipped = parse_snapshot(snapshot(*rows))
    assert skipped == 0
    return found


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[Any]:
    engine = create_engine(database_url)
    yield engine
    await engine.dispose()


def outages(engine: Any, now: datetime = NOW) -> VoeOutages:
    return VoeOutages(engine, clock=lambda: now)


async def test_an_imported_row_is_read_back_by_the_catalogue_ids_in_utc(engine: Any) -> None:
    await outages(engine).replace(parsed(EMERGENCY, PLANNED), NOW)

    assert await outages(engine).emergency_outages(CITY, STREET) == [
        PlannedWork(
            id=1,
            street_id=STREET,
            starts_at=datetime(2026, 11, 26, 8, 37, tzinfo=UTC),
            ends_at=datetime(2026, 11, 26, 15, 0, tzinfo=UTC),
            reason="Аварійний випадок в мережах",
            building_names=("1", "1А"),
        )
    ]
    [planned] = await outages(engine).planned_works(CITY, STREET, NOW)
    assert planned.building_names == ("3",)


async def test_planned_works_ended_before_after_are_left_out(engine: Any) -> None:
    await outages(engine).replace(parsed(PLANNED), NOW)

    later = datetime(2026, 11, 26, 14, 0, tzinfo=UTC)  # 16:00 in Kyiv, the planned end
    assert await outages(engine, later).planned_works(CITY, STREET, later) == []


async def test_a_new_snapshot_replaces_the_old_one(engine: Any) -> None:
    await outages(engine).replace(parsed(EMERGENCY), NOW)
    await outages(engine).replace(parsed(), NOW)

    assert await outages(engine).emergency_outages(CITY, STREET) == []


async def test_a_snapshot_older_than_an_hour_is_ignored(engine: Any) -> None:
    await outages(engine).replace(parsed(EMERGENCY), NOW)

    assert await outages(engine, NOW + MAX_AGE - timedelta(seconds=1)).emergency_outages(
        CITY, STREET
    )
    assert (
        await outages(engine, NOW + MAX_AGE + timedelta(seconds=1)).emergency_outages(CITY, STREET)
        == []
    )


async def test_no_snapshot_yet_means_nothing(engine: Any) -> None:
    assert await outages(engine).emergency_outages(CITY, STREET) == []


async def test_the_weekly_catalogue_import_keeps_the_snapshot(engine: Any) -> None:
    await outages(engine).replace(parsed(EMERGENCY), NOW)

    await VoeCatalog(engine).replace(
        [CatalogRow("Луцький", "Ківерці", "Європейська", "1", "6.1")], NOW
    )

    assert await outages(engine).emergency_outages(CITY, STREET)


def test_an_odd_row_is_skipped_and_the_rest_kept() -> None:
    too_long = [*EMERGENCY[:7], "п" * 300]

    found, skipped = parse_snapshot(snapshot(too_long, PLANNED))

    assert [row.building_names for row in found] == [("3",)]
    assert skipped == 1


def test_an_empty_snapshot_is_no_outages() -> None:
    assert parse_snapshot(snapshot()) == ([], 0)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        snapshot(EMERGENCY[:7]),
        snapshot([*EMERGENCY[:4], "gpv", *EMERGENCY[5:]]),
        snapshot([*EMERGENCY[:5], "26.11.2026 10:37", *EMERGENCY[6:]]),
        snapshot([*EMERGENCY[:3], [], *EMERGENCY[4:]]),
        json.dumps({"rows": [], "extra": 1}).encode(),
    ],
    ids=[
        "not-json",
        "short-row",
        "unknown-kind",
        "bad-time",
        "no-buildings",
        "extra-key",
    ],
)
def test_anything_but_an_export_is_refused(raw: bytes) -> None:
    with pytest.raises(OutagesImportRefused):
        parse_snapshot(raw)

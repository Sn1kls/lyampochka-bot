import gzip
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from poweron.adapters.db.repository import SqlRepository, create_engine
from poweron.adapters.db.voe_catalog import (
    CatalogImportRefused,
    CatalogRow,
    VoeCatalog,
    parse_export,
)
from poweron.core.domain.models import Building
from poweron.core.domain.providers import VOE_CATALOG_IMPORTED_KEY
from tests.services.conftest import NOW

ROWS = [
    CatalogRow("Луцький", "Ківерці", "Незалежності", "19", "6.1"),
    CatalogRow("Луцький", "Ківерці", "Незалежності", "20", "6.1"),
    CatalogRow("Луцький", "Ківерці", "Незалежності", "20", "2.2"),
    CatalogRow("Луцький", "Ківерці", "Незалежності", "21", None),
    CatalogRow("Луцький", "Ківерці", "Незалежності", "21", "3.1"),
    CatalogRow("Луцький", "Ківерці", "Незалежності", "22", None),
    CatalogRow("Луцький", "Ківерці", "Шевченка", "1", "1.1"),
    CatalogRow("Ковельський", "Ківерці", "Шевченка", "1", "4.2"),
]


def export(rows: list[Any]) -> bytes:
    return gzip.compress(json.dumps({"rows": rows}, ensure_ascii=False).encode())


@pytest.fixture
async def catalog(database_url: str) -> AsyncIterator[VoeCatalog]:
    engine = create_engine(database_url)
    yield VoeCatalog(engine)
    await engine.dispose()


async def kivertsi_nezalezhnosti(catalog: VoeCatalog) -> tuple[int, int]:
    [city] = [city for city in await catalog.cities() if city.otg_name == "Луцький р-н"]
    [street] = [
        street for street in await catalog.streets(city.id) if street.name == "Незалежності"
    ]
    return city.id, street.id


def test_parse_export_reads_the_export_format() -> None:
    rows = parse_export(export([["Луцький", "Ківерці", "Незалежності", "19", "6.1"]]))

    assert rows == [CatalogRow("Луцький", "Ківерці", "Незалежності", "19", "6.1")]


@pytest.mark.parametrize(
    "broken",
    [
        b"not gzip",
        gzip.compress(b"not json"),
        export([["Луцький", "Ківерці", "Незалежності", "19"]]),
        export([["Луцький", "Ківерці", "Незалежності", "19", "7.1"]]),
        export([["Луцький", "", "Незалежності", "19", "6.1"]]),
        export([["Луцький", "Ківерці", "Незалежності", "x" * 65, "6.1"]]),
    ],
)
def test_parse_export_refuses_a_malformed_file(broken: bytes) -> None:
    with pytest.raises(CatalogImportRefused):
        parse_export(broken)


async def test_same_named_settlements_of_two_districts_stay_apart(catalog: VoeCatalog) -> None:
    await catalog.replace(ROWS, NOW)

    cities = sorted((city.name, city.otg_name) for city in await catalog.cities())

    assert cities == [("Ківерці", "Ковельський р-н"), ("Ківерці", "Луцький р-н")]


async def test_buildings_carry_their_namespaced_queues(catalog: VoeCatalog) -> None:
    await catalog.replace(ROWS, NOW)
    city_id, street_id = await kivertsi_nezalezhnosti(catalog)

    buildings = {
        building.name: building for building in await catalog.buildings(city_id, street_id)
    }

    assert buildings["19"].cherg_gpv == "voe:6.1"
    assert buildings["22"].cherg_gpv is None  # «Не залучено»
    assert await catalog.building_subqueues(city_id, street_id, "20") == ["voe:2.2", "voe:6.1"]
    # «Не залучено» in one row and a queue in another: the building is in that queue.
    assert await catalog.building_subqueues(city_id, street_id, "21") == ["voe:3.1"]
    assert await catalog.building_subqueues(city_id, street_id, "99") == []


async def test_ids_survive_a_reimport(catalog: VoeCatalog) -> None:
    await catalog.replace(ROWS, NOW)
    before = await kivertsi_nezalezhnosti(catalog)
    [building] = [b for b in await catalog.buildings(*before) if b.name == "19"]

    await catalog.replace(list(reversed(ROWS)), NOW)

    assert await kivertsi_nezalezhnosti(catalog) == before
    assert Building(building.id, "19", "voe:6.1") in await catalog.buildings(*before)


async def test_a_reimport_replaces_rows_and_counts_changed_buildings(
    catalog: VoeCatalog, repository: SqlRepository
) -> None:
    first = await catalog.replace(ROWS, NOW)
    moved = [*ROWS[1:], CatalogRow("Луцький", "Ківерці", "Незалежності", "19", "5.2")]
    second = await catalog.replace(moved, NOW)

    assert (first.buildings, first.previous_buildings, first.changed) == (6, 0, 6)
    assert (second.buildings, second.previous_buildings, second.changed) == (6, 6, 1)
    assert await catalog.count() == len(moved)
    city_id, street_id = await kivertsi_nezalezhnosti(catalog)
    assert await catalog.building_subqueues(city_id, street_id, "19") == ["voe:5.2"]
    cached = await repository.cached_catalog(VOE_CATALOG_IMPORTED_KEY)
    assert cached is not None and cached[1] == NOW


async def test_a_much_smaller_export_is_refused_unless_forced(catalog: VoeCatalog) -> None:
    await catalog.replace(ROWS, NOW)

    with pytest.raises(CatalogImportRefused):
        await catalog.replace(ROWS[:1], NOW)
    assert await catalog.count() == len(ROWS)

    await catalog.replace(ROWS[:1], NOW, force=True)
    assert await catalog.count() == 1

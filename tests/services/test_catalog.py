from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import Building, City, Street
from poweron.core.ports import SourceUnavailable
from poweron.core.services.catalog import Catalog, find_building
from tests.services.conftest import NOW

TERNOPIL = City(id=1, name="Тернопіль", otg_name="Тернопільська")
CITIES = [
    City(id=2, name="смт Козова", otg_name=None),
    City(id=3, name="с. Острів", otg_name=None),
    City(id=4, name="Бережани", otg_name=None),
    TERNOPIL,
    City(id=5, name="Нова Тернопільська", otg_name=None),
    City(id=6, name="Єнакієве", otg_name=None),
]
STREETS = [
    Street(id=1, name="вул. Садова"),
    Street(id=2, name="вул. Ґаґаріна"),
    Street(id=3, name="просп. Степана Бандери"),
    Street(id=4, name="вул. Об'їзна"),
    Street(id=5, name="вул. Лісова Садова"),
]
BUILDINGS = [Building(1, "1", "4.1"), Building(2, "1А", "4.1"), Building(3, "23", None)]


@dataclass
class FakeCatalogSource:
    failing: bool = False
    city_calls: int = 0
    street_calls: list[int] = field(default_factory=list)

    async def cities(self) -> list[City]:
        self.city_calls += 1
        if self.failing:
            raise SourceUnavailable("down")
        return CITIES

    async def streets(self, city_id: int) -> list[Street]:
        self.street_calls.append(city_id)
        return STREETS

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        return BUILDINGS


@pytest.fixture
def source() -> FakeCatalogSource:
    return FakeCatalogSource()


@pytest.fixture
def catalog(repository: SqlRepository, source: FakeCatalogSource) -> Catalog:
    return Catalog(repository, source)


async def test_cities_match_by_normalised_substring_prefix_matches_first(
    catalog: Catalog,
) -> None:
    found = await catalog.find_cities("  ТЕРНОП ", NOW)
    assert [city.name for city in found] == ["Тернопіль", "Нова Тернопільська"]


async def test_prefix_matches_and_the_rest_are_each_sorted_alphabetically(
    catalog: Catalog,
) -> None:
    found = await catalog.find_streets(1, "с", NOW)
    assert [street.id for street in found] == [1, 3, 5]


async def test_leading_type_prefix_is_ignored_on_both_sides(catalog: Catalog) -> None:
    assert [city.id for city in await catalog.find_cities("козова", NOW)] == [2]
    assert [city.id for city in await catalog.find_cities("смт козова", NOW)] == [2]
    assert [city.id for city in await catalog.find_cities("с. острів", NOW)] == [3]
    streets = await catalog.find_streets(1, "вул. садова", NOW)
    assert [street.id for street in streets] == [1, 5]


async def test_apostrophes_are_unified(catalog: Catalog) -> None:
    for query in ("об’їзна", "обʼїзна", "об`їзна", "об‘їзна", "об'їзна"):
        assert [street.id for street in await catalog.find_streets(1, query, NOW)] == [4]


async def test_ye_and_latin_lookalikes_are_unified(catalog: Catalog) -> None:
    for query in ("єнакієве", "енакієве", "ёнакієве", "Eнaкiєвe"):
        assert [city.id for city in await catalog.find_cities(query, NOW)] == [6]
    assert [street.id for street in await catalog.find_streets(1, "Лiсова", NOW)] == [5]


async def test_blank_query_finds_nothing(catalog: Catalog) -> None:
    assert await catalog.find_cities("   ", NOW) == []
    assert await catalog.find_cities("", NOW) == []


async def test_catalog_is_cached_for_a_day(catalog: Catalog, source: FakeCatalogSource) -> None:
    await catalog.find_cities("тер", NOW)
    await catalog.find_cities("тер", NOW + timedelta(hours=23))
    assert source.city_calls == 1
    await catalog.find_cities("тер", NOW + timedelta(hours=25))
    assert source.city_calls == 2


async def test_cached_values_are_rebuilt_into_domain_objects(catalog: Catalog) -> None:
    await catalog.find_cities("тер", NOW)
    assert (await catalog.find_cities("тернопіль", NOW))[0] == TERNOPIL
    assert await catalog.buildings(1, 1, NOW) == BUILDINGS
    assert await catalog.buildings(1, 1, NOW) == BUILDINGS


async def test_streets_are_cached_per_city(catalog: Catalog, source: FakeCatalogSource) -> None:
    await catalog.find_streets(1, "са", NOW)
    await catalog.find_streets(1, "са", NOW)
    await catalog.find_streets(2, "са", NOW)
    assert source.street_calls == [1, 2]


async def test_stale_cache_is_served_when_the_source_fails(
    catalog: Catalog, source: FakeCatalogSource
) -> None:
    await catalog.find_cities("тер", NOW)
    source.failing = True
    assert TERNOPIL in await catalog.find_cities("тер", NOW + timedelta(days=3))


async def test_failed_refresh_is_not_retried_for_five_minutes(
    catalog: Catalog, source: FakeCatalogSource
) -> None:
    await catalog.find_cities("тер", NOW)
    source.failing = True
    stale = NOW + timedelta(days=3)
    await catalog.find_cities("тер", stale)
    await catalog.find_cities("тер", stale + timedelta(minutes=4))
    assert source.city_calls == 2
    await catalog.find_cities("тер", stale + timedelta(minutes=6))
    assert source.city_calls == 3


async def test_recovered_source_refreshes_the_cache(
    catalog: Catalog, source: FakeCatalogSource
) -> None:
    await catalog.find_cities("тер", NOW)
    source.failing = True
    stale = NOW + timedelta(days=3)
    await catalog.find_cities("тер", stale)
    source.failing = False
    await catalog.find_cities("тер", stale + timedelta(minutes=6))
    await catalog.find_cities("тер", stale + timedelta(minutes=7))
    assert source.city_calls == 3


async def test_storing_a_key_twice_keeps_the_latest_value(repository: SqlRepository) -> None:
    await repository.store_catalog("cities", [{"id": 1}], NOW)
    await repository.store_catalog("cities", [{"id": 2}], NOW + timedelta(hours=1))
    assert await repository.cached_catalog("cities") == ([{"id": 2}], NOW + timedelta(hours=1))


async def test_source_error_without_cache_is_raised(
    catalog: Catalog, source: FakeCatalogSource
) -> None:
    source.failing = True
    with pytest.raises(SourceUnavailable):
        await catalog.find_cities("тер", NOW)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1а", 2),
        (" 1А ", 2),
        ("1a", 2),
        ("буд. 23", 3),
        ("БУД 1", 1),
        ("2", None),
        ("", None),
    ],
)
def test_find_building_matches_the_normalised_name_exactly(text: str, expected: int | None) -> None:
    found = find_building(BUILDINGS, text)
    assert (found.id if found else None) == expected

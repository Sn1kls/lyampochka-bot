from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timedelta

from poweron.core.domain.models import Building, City, Street
from poweron.core.domain.text import normalise
from poweron.core.ports import CatalogSource, Repository, SourceError

CACHE_TTL = timedelta(hours=24)
FAILED_REFRESH_BACKOFF = timedelta(minutes=5)


class Catalog:
    def __init__(self, repository: Repository, source: CatalogSource) -> None:
        self._repository = repository
        self._source = source
        self._failed_refresh_at: dict[str, datetime] = {}

    async def find_cities(self, query: str, now: datetime) -> list[City]:
        cities = await self._cached("cities", City, self._source.cities, now)
        return _search(cities, query)

    async def find_streets(self, city_id: int, query: str, now: datetime) -> list[Street]:
        streets = await self._cached(
            f"streets:{city_id}", Street, lambda: self._source.streets(city_id), now
        )
        return _search(streets, query)

    async def buildings(self, city_id: int, street_id: int, now: datetime) -> list[Building]:
        return await self._cached(
            f"buildings:{city_id}:{street_id}",
            Building,
            lambda: self._source.buildings(city_id, street_id),
            now,
        )

    async def subqueues(self, city_id: int, street_id: int, building: Building) -> list[str]:
        """All subqueues of the building; empty when schedules do not apply to it."""
        if building.cherg_gpv is None:
            return []
        found = await self._source.building_subqueues(city_id, street_id, building.name)
        return found or [building.cherg_gpv]

    async def _cached[Item: (City, Street, Building)](
        self,
        key: str,
        item_type: Callable[..., Item],
        fetch: Callable[[], Awaitable[list[Item]]],
        now: datetime,
    ) -> list[Item]:
        cached = await self._repository.cached_catalog(key)
        if cached is not None:
            stored, fetched_at = cached
            cached_items = [item_type(**fields) for fields in stored]
            if now - fetched_at < CACHE_TTL:
                return cached_items
            failed_at = self._failed_refresh_at.get(key)
            if failed_at is not None and now - failed_at < FAILED_REFRESH_BACKOFF:
                return cached_items
        try:
            items = await fetch()
        except SourceError:
            if cached is None:
                raise
            self._failed_refresh_at[key] = now
            return cached_items
        self._failed_refresh_at.pop(key, None)
        await self._repository.store_catalog(key, [asdict(item) for item in items], now)
        return items


def find_by_name[Item: (City, Street, Building)](items: list[Item], text: str) -> Item | None:
    """The item whose name is exactly what the user typed, if there is exactly one."""
    wanted = normalise(text)
    matches = [item for item in items if normalise(item.name) == wanted]
    return matches[0] if len(matches) == 1 else None


def _search[Item: (City, Street)](items: list[Item], query: str) -> list[Item]:
    wanted = normalise(query)
    if not wanted:
        return []
    matches = [(normalise(item.name), item) for item in items]
    matches = [match for match in matches if wanted in match[0]]
    matches.sort(key=lambda match: (not match[0].startswith(wanted), match[0]))
    return [item for _, item in matches]

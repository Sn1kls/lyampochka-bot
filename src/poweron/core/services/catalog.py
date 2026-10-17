import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timedelta

from poweron.core.domain.models import Building, City, Street
from poweron.core.ports import CatalogSource, Repository, SourceError

CACHE_TTL = timedelta(hours=24)
FAILED_REFRESH_BACKOFF = timedelta(minutes=5)
# Apostrophes, Ukrainian/Russian spelling variants and Latin letters typed instead of Cyrillic
SPELLING = str.maketrans(
    {"ʼ": "'", "’": "'", "‘": "'", "`": "'", "ё": "е", "є": "е"}
    | dict(zip("aeiocpxk", "аеіосрхк", strict=True))
)
TYPE_PREFIX = re.compile(r"^(вул|просп|пров|бул|пл|м|с|смт|буд)\.?\s+")


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


def find_building(buildings: list[Building], text: str) -> Building | None:
    wanted = _normalise(text)
    return next((item for item in buildings if _normalise(item.name) == wanted), None)


def _normalise(text: str) -> str:
    text = text.casefold().translate(SPELLING)
    return TYPE_PREFIX.sub("", " ".join(text.split()))


def _search[Item: (City, Street)](items: list[Item], query: str) -> list[Item]:
    wanted = _normalise(query)
    if not wanted:
        return []
    matches = [(_normalise(item.name), item) for item in items]
    matches = [match for match in matches if wanted in match[0]]
    matches.sort(key=lambda match: (not match[0].startswith(wanted), match[0]))
    return [item for _, item in matches]

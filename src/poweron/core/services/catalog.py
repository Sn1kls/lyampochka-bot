from datetime import datetime

from poweron.core.domain.models import Building, City, Street
from poweron.core.ports import CatalogSource, Repository


class Catalog:
    def __init__(self, repository: Repository, source: CatalogSource) -> None:
        self._repository = repository
        self._source = source

    async def find_cities(self, query: str, now: datetime) -> list[City]:
        raise NotImplementedError

    async def find_streets(self, city_id: int, query: str, now: datetime) -> list[Street]:
        raise NotImplementedError

    async def buildings(self, city_id: int, street_id: int, now: datetime) -> list[Building]:
        raise NotImplementedError


def find_building(buildings: list[Building], text: str) -> Building | None:
    raise NotImplementedError

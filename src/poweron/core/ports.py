from typing import Protocol

from poweron.core.domain.models import Address, Building, City, DaySchedule, Street


class SourceError(Exception):
    """The schedule/catalog source failed; services fall back to cached data."""


class SourceUnavailable(SourceError):
    """Network error, timeout, or an error status after retries."""


class ApiSchemaError(SourceError):
    """The response no longer matches the expected format."""


class ScheduleSource(Protocol):
    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """Today's and (if published) tomorrow's schedules for the address, by day."""
        ...


class CatalogSource(Protocol):
    async def cities(self) -> list[City]: ...

    async def streets(self, city_id: int) -> list[Street]: ...

    async def buildings(self, city_id: int, street_id: int) -> list[Building]: ...

import asyncio
import logging
import time
import zlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from poweron.adapters.loe_api.schedule import GROUPS, LoeSchedule, parse_schedule
from poweron.adapters.paced_http import PacedHttp
from poweron.core.domain.models import KYIV, Address, Building, City, DaySchedule, Street
from poweron.core.domain.providers import LOE, plain_subqueue, scoped_subqueue
from poweron.core.domain.schedule import day_slots
from poweron.core.ports import ApiSchemaError, SourceError

CONTENT_API = "https://api.loe.lviv.ua/api"
POWER_API = "https://power-api.loe.lviv.ua/api"
# The site's "photo-grafic" menu: today's and tomorrow's schedule text.
SCHEDULE_ITEMS = (238, 256)
CACHE_SECONDS = 60.0
NO_SCHEDULE = {"", "Не входить"}

logger = logging.getLogger(__name__)


class _MenuItem(BaseModel):
    rawHtml: str


class _Otg(BaseModel):
    name: str


class _City(BaseModel):
    id: int
    name: str
    otg: _Otg | None = None


class _Street(BaseModel):
    id: int
    name: str


class _Account(BaseModel):
    """One consumer account; a building has as many rows as accounts."""

    buildingName: str
    chergGpv: str | None = None


_MENU_ITEM = TypeAdapter(_MenuItem)
_CITIES = TypeAdapter(list[_City])
_STREETS = TypeAdapter(list[_Street])
_ACCOUNTS = TypeAdapter(list[_Account])


class LoeClient:
    def __init__(
        self,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(KYIV),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = PacedHttp(
            httpx.AsyncClient(
                headers={"User-Agent": f"poweron-bot/{version('poweron')} (personal use)"},
                timeout=30,
            ),
            monotonic,
            sleep,
        )
        self._now = now
        self._monotonic = monotonic
        self._cache_lock = asyncio.Lock()
        self._current: tuple[float, date, dict[date, LoeSchedule]] | None = None
        self._failure: tuple[float, SourceError] | None = None
        # `/add` lists a street's buildings, then asks the queues of one of them; the daily
        # queue re-check goes building by building, streets mixed.
        self._streets: dict[tuple[int, int], tuple[float, dict[str, list[str]]]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def cities(self) -> list[City]:
        cities = await self._list("pw_cities", {"otg.id": ""}, _CITIES)
        return [
            City(id=city.id, name=city.name, otg_name=city.otg.name if city.otg else None)
            for city in cities
        ]

    async def streets(self, city_id: int) -> list[Street]:
        streets = await self._list("pw_streets", {"city.id": city_id}, _STREETS)
        return [Street(id=street.id, name=street.name) for street in streets]

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        return [
            Building(id=_stable_id(name), name=name, cherg_gpv=queues[0] if queues else None)
            for name, queues in (await self._street_queues(city_id, street_id)).items()
        ]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        return (await self._street_queues(city_id, street_id)).get(building_name, [])

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """The address is ignored: one text holds every group."""
        group = plain_subqueue(cherg_gpv)
        if group not in GROUPS:
            return []
        return [
            DaySchedule(
                cherg_gpv=cherg_gpv,
                day=day,
                created_at=schedule.published_at,
                slots=day_slots(schedule.groups[group]),
            )
            for day, schedule in sorted((await self._current_schedules()).items())
        ]

    async def _current_schedules(self) -> dict[date, LoeSchedule]:
        today = self._now().astimezone(KYIV).date()
        async with self._cache_lock:
            if self._current:
                expires_at, cached_day, schedules = self._current
                if cached_day == today and self._monotonic() < expires_at:
                    return schedules
            # One failed pass is enough: the other subqueues of this poll fail at once.
            if self._failure and self._monotonic() < self._failure[0]:
                raise type(self._failure[1])(str(self._failure[1]))
            try:
                schedules = await self._fetch_schedules(today)
            except SourceError as error:
                self._failure = (self._monotonic() + CACHE_SECONDS, error)
                raise
            self._failure = None
            self._current = (self._monotonic() + CACHE_SECONDS, today, schedules)
            return schedules

    async def _fetch_schedules(self, today: date) -> dict[date, LoeSchedule]:
        readable = []
        errors: list[ApiSchemaError] = []
        for item_id in SCHEDULE_ITEMS:
            response = await self._http.get(
                f"{CONTENT_API}/menu_items/{item_id}",
                {},
                {"Accept": "application/ld+json"},
                json=True,
            )
            try:
                schedule = parse_schedule(
                    _validate(_MENU_ITEM, response.json(), "menu_items").rawHtml
                )
            except ApiSchemaError as error:
                # A half-edited «Tomorrow» must not hide today; nothing usable left is an outage.
                errors.append(error)
                logger.error("loe schedule item %s skipped: %s", item_id, error)
                continue
            # Either item may hold a stale or a mistyped day around midnight.
            if schedule is not None and schedule.day in (today, today + timedelta(days=1)):
                readable.append(schedule)
        if errors and not readable:
            raise errors[0]
        # The later text of a day wins.
        return {
            schedule.day: schedule
            for schedule in sorted(readable, key=lambda schedule: schedule.published_at)
        }

    async def _street_queues(self, city_id: int, street_id: int) -> dict[str, list[str]]:
        """Queues by building name; «Не входить» next to a queue in another row counts as in it."""
        now = self._monotonic()
        self._streets = {key: cached for key, cached in self._streets.items() if now < cached[0]}
        if cached := self._streets.get((city_id, street_id)):
            return cached[1]
        accounts = await self._list(
            "pw_accounts", {"city.id": city_id, "street.id": street_id}, _ACCOUNTS
        )
        found: dict[str, set[str]] = defaultdict(set)
        for account in accounts:
            name = account.buildingName.strip()
            if not name:
                continue
            subqueues = found[name]
            queue = (account.chergGpv or "").strip()
            if queue in GROUPS:
                subqueues.add(scoped_subqueue(LOE, queue))
            elif queue not in NO_SCHEDULE:
                logger.warning("loe: unknown queue value %r taken as no queue", queue[:40])
        queues = {name: sorted(subqueues) for name, subqueues in found.items()}
        self._streets[(city_id, street_id)] = (now + CACHE_SECONDS, queues)
        return queues

    async def _list[Model](
        self, endpoint: str, params: dict[str, Any], adapter: TypeAdapter[list[Model]]
    ) -> list[Model]:
        response = await self._http.get(
            f"{POWER_API}/{endpoint}",
            {"pagination": "false"} | params,
            {"Accept": "application/ld+json"},
            json=True,
        )
        data = response.json()
        # Some endpoints answer a hydra collection, others a bare list.
        if isinstance(data, dict):
            data = data.get("hydra:member")
        return _validate(adapter, data, endpoint)


def _validate[Model](adapter: TypeAdapter[Model], data: Any, endpoint: str) -> Model:
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise ApiSchemaError.from_validation(f"loe {endpoint}", error) from None


def _stable_id(building_name: str) -> int:
    """Account rows carry no building id; the name gives one that survives a refetch."""
    return zlib.crc32(building_name.encode()) & 0x7FFFFFFF

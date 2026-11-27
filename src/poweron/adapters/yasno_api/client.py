import asyncio
import logging
import re
import time
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from poweron.adapters.paced_http import PacedHttp
from poweron.core.domain.models import KYIV, Address, Building, City, DaySchedule, Street
from poweron.core.domain.providers import (
    CEK,
    DNEM,
    plain_subqueue,
    provider_of,
    scoped_subqueue,
)
from poweron.core.domain.schedule import day_slots
from poweron.core.domain.text import normalise
from poweron.core.ports import ApiSchemaError, SourceError

API = "https://app.yasno.ua/api/blackout-service/public/shutdowns"
REGION_ID = 3  # «Дніпро» in YASNO's region list: the whole oblast
DSO_IDS = {DNEM: 301, CEK: 303}
CACHE_SECONDS = 60.0
SLOT_MINUTES = 30
DAY_MINUTES = 24 * 60
OFF, ON = "1", "0"
SLOT_CODES = {"Definite": OFF, "NotPlanned": ON}
WITH_SCHEDULE = {"ScheduleApplies", "NoOutages"}
WAITING = "WaitingForSchedule"
SUSPENDED = "EmergencyShutdowns"
# A city or street of both operators is one item whose id carries both ids (0: absent).
# ponytail: ids up to 10^10 fit SQLite's INTEGER; Postgres would need BIGINT for them.
PAIR_BASE = 100_000
# YASNO answers nothing to a shorter street query.
MIN_STREET_QUERY = 3
# «1 ввод 2»: the second power input of house 1, listed as a house of its own.
INPUT = re.compile(r"\s+ввод\s+\d+$", re.IGNORECASE)

logger = logging.getLogger(__name__)


class _Slot(BaseModel):
    start: int
    end: int
    type: str


class _Day(BaseModel):
    date: datetime
    status: str
    slots: list[_Slot] = []


class _Named(BaseModel):
    id: int
    value: str


class _HouseGroup(BaseModel):
    group: int
    subgroup: int


_NAMED = TypeAdapter(list[_Named])
_HOUSE_GROUP = TypeAdapter(_HouseGroup)


class _Group(BaseModel):
    today: _Day | None = None
    tomorrow: _Day | None = None
    updatedOn: datetime


_SCHEDULE = TypeAdapter(dict[str, _Group])


class YasnoClient:
    """Both Dnipropetrovsk operators (DTEK DnEM and CEK) through YASNO's public API."""

    def __init__(
        self,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(KYIV),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_suspended: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        """`on_suspended` hears of an operator's emergency shutdowns once a day (the admin)."""
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
        # provider → (expires at, groups); one request a minute covers all of its groups.
        self._schedules: dict[str, tuple[float, dict[str, _Group]]] = {}
        self._failures: dict[str, tuple[float, SourceError]] = {}
        self._on_suspended = on_suspended
        self._suspended_seen: set[tuple[str, date]] = set()
        # `/add` searches a number, then asks the picked house's queues: one request, not two.
        self._houses_cache: dict[tuple[str, int, int, str], tuple[float, list[_Named]]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """The address is ignored: the operator's answer holds every group."""
        group = (await self._groups(provider_of(cherg_gpv))).get(plain_subqueue(cherg_gpv))
        if group is None:
            return []
        today = self._now().astimezone(KYIV).date()
        schedules = []
        for day in (group.today, group.tomorrow):
            if day is None or day.date.date() not in (today, today + timedelta(days=1)):
                continue
            if day.status == WAITING:
                continue
            if day.status == SUSPENDED:
                await self._report_suspended(provider_of(cherg_gpv), day.date.date())
                continue
            if day.status not in WITH_SCHEDULE:
                raise ApiSchemaError(f"yasno {cherg_gpv}: unknown day status {day.status!r}")
            schedules.append(
                DaySchedule(
                    cherg_gpv=cherg_gpv,
                    day=day.date.date(),
                    created_at=group.updatedOn.astimezone(KYIV),
                    slots=day_slots(_codes(cherg_gpv, day)),
                )
            )
        return schedules

    async def _report_suspended(self, provider: str, day: date) -> None:
        """Not seen live yet: the admin should hear of it, once per operator and day."""
        if (provider, day) in self._suspended_seen:
            return
        self._suspended_seen.add((provider, day))
        logger.warning("yasno %s: emergency shutdowns on %s", provider, day)
        if self._on_suspended is not None:
            await self._on_suspended(f"{provider} {day}")

    async def suspended(self, cherg_gpv: str) -> bool:
        """Today is emergency shutdowns: the operator says no schedule applies."""
        group = (await self._groups(provider_of(cherg_gpv))).get(plain_subqueue(cherg_gpv))
        today = self._now().astimezone(KYIV).date()
        return group is not None and any(
            day is not None and day.status == SUSPENDED and day.date.date() == today
            for day in (group.today, group.tomorrow)
        )

    async def cities(self) -> list[City]:
        named = {
            provider: await self._addresses("cities", provider, {"query": ""})
            for provider in DSO_IDS
        }
        return [City(id=item_id, name=name, otg_name=None) for item_id, name in _merge(named)]

    async def search_streets(self, city_id: int, query: str) -> list[Street]:
        query = " ".join(query.split())
        if len(query) < MIN_STREET_QUERY:
            return []
        named = {
            provider: await self._addresses(
                "streets", provider, {"cityId": provider_city, "query": query}
            )
            for provider, provider_city in _unpair(city_id).items()
        }
        return [Street(id=item_id, name=name) for item_id, name in _merge(named)]

    async def search_buildings(self, city_id: int, street_id: int, query: str) -> list[Building]:
        """Every input of a house is one building; its queues are asked once it is picked."""
        names: dict[str, str] = {}
        for _, house in await self._houses(city_id, street_id, query):
            name = _house_name(house)
            names.setdefault(normalise(name), name)
        return [Building(id=_stable_id(name), name=name, cherg_gpv=None) for name in names.values()]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        cities, streets = _unpair(city_id), _unpair(street_id)
        wanted = normalise(building_name)
        subqueues = set()
        for provider, house in await self._houses(city_id, street_id, building_name):
            if normalise(_house_name(house)) != wanted:
                continue
            response = await self._http.get(
                f"{API}/addresses/v2/group",
                {
                    "regionId": REGION_ID,
                    "dsoId": DSO_IDS[provider],
                    "cityId": cities[provider],
                    "streetId": streets[provider],
                    "houseId": house.id,
                },
                {"Accept": "application/json"},
                json=True,
            )
            found = _validate(_HOUSE_GROUP, response.json(), "group")
            subqueues.add(scoped_subqueue(provider, f"{found.group}.{found.subgroup}"))
        return sorted(subqueues)

    async def _houses(self, city_id: int, street_id: int, query: str) -> list[tuple[str, _Named]]:
        cities = _unpair(city_id)
        found = []
        now = self._monotonic()
        self._houses_cache = {
            key: cached for key, cached in self._houses_cache.items() if now < cached[0]
        }
        for provider, provider_street in _unpair(street_id).items():
            key = (provider, cities[provider], provider_street, query.strip())
            if (cached := self._houses_cache.get(key)) is None:
                houses = await self._addresses(
                    "houses",
                    provider,
                    {"cityId": key[1], "streetId": key[2], "query": key[3]},
                )
                cached = (now + CACHE_SECONDS, houses)
                self._houses_cache[key] = cached
            found += [(provider, house) for house in cached[1]]
        return found

    async def _addresses(
        self, endpoint: str, provider: str, params: dict[str, Any]
    ) -> list[_Named]:
        response = await self._http.get(
            f"{API}/addresses/v2/{endpoint}",
            {"regionId": REGION_ID, "dsoId": DSO_IDS[provider]} | params,
            {"Accept": "application/json"},
            json=True,
        )
        return _validate(_NAMED, response.json(), endpoint)

    async def _groups(self, provider: str) -> dict[str, _Group]:
        async with self._cache_lock:
            now = self._monotonic()
            if (cached := self._schedules.get(provider)) and now < cached[0]:
                return cached[1]
            # One failed request is enough: the other groups of this poll fail at once.
            if (failure := self._failures.get(provider)) and now < failure[0]:
                raise type(failure[1])(str(failure[1]))
            try:
                response = await self._http.get(
                    f"{API}/regions/{REGION_ID}/dsos/{DSO_IDS[provider]}/planned-outages",
                    {},
                    {"Accept": "application/json"},
                    json=True,
                )
                groups = _validate(_SCHEDULE, response.json(), "planned-outages")
            except SourceError as error:
                self._failures[provider] = (self._monotonic() + CACHE_SECONDS, error)
                raise
            self._failures.pop(provider, None)
            self._schedules[provider] = (self._monotonic() + CACHE_SECONDS, groups)
            return groups


@dataclass
class _Merged:
    name: str
    ids: dict[str, int] = field(default_factory=dict)  # provider → its own id


def _merge(named: dict[str, list[_Named]]) -> list[tuple[int, str]]:
    """(pair id, name): a name both operators list becomes one item, named as DnEM writes it."""
    merged: list[_Merged] = []
    by_name: dict[str, _Merged] = {}
    for provider in (DNEM, CEK):
        for item in named.get(provider, []):
            if not 0 < item.id < PAIR_BASE:
                raise ApiSchemaError(f"yasno: id {item.id} does not fit a pair id")
            entry = by_name.get(normalise(item.value))
            # One operator's own duplicates stay apart: only the other operator merges in.
            if entry is None or provider in entry.ids:
                entry = _Merged(item.value.strip())
                merged.append(entry)
                by_name.setdefault(normalise(item.value), entry)
            entry.ids[provider] = item.id
    return [
        (entry.ids.get(DNEM, 0) * PAIR_BASE + entry.ids.get(CEK, 0), entry.name) for entry in merged
    ]


def _unpair(pair_id: int) -> dict[str, int]:
    """The operators' own ids behind a pair id, for the operators that have the item."""
    ids = {DNEM: pair_id // PAIR_BASE, CEK: pair_id % PAIR_BASE}
    return {provider: item_id for provider, item_id in ids.items() if item_id}


def _house_name(house: _Named) -> str:
    return INPUT.sub("", house.value.strip())


def _stable_id(name: str) -> int:
    """Inputs merge into one building, so it takes its id from the name."""
    return zlib.crc32(name.encode()) & 0x7FFFFFFF


def _codes(cherg_gpv: str, day: _Day) -> list[str]:
    """48 half-hour codes from the day's minute intervals; anything off the grid is an error."""
    codes = [ON] * (DAY_MINUTES // SLOT_MINUTES)
    for slot in day.slots:
        code = SLOT_CODES.get(slot.type)
        if (
            code is None
            or not 0 <= slot.start < slot.end <= DAY_MINUTES
            or slot.start % SLOT_MINUTES
            or slot.end % SLOT_MINUTES
        ):
            raise ApiSchemaError(f"yasno {cherg_gpv}: unexpected slot {slot}")
        for index in range(slot.start // SLOT_MINUTES, slot.end // SLOT_MINUTES):
            codes[index] = code
    return codes


def _validate[Model](adapter: TypeAdapter[Model], data: Any, endpoint: str) -> Model:
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise ApiSchemaError.from_validation(f"yasno {endpoint}", error) from None

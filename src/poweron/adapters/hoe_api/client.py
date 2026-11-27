import asyncio
import logging
import re
import time
import zlib
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from importlib.metadata import version

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from poweron.adapters.hoe_api.schedule import SUBQUEUES, announced_day, parse_archive, parse_post
from poweron.adapters.paced_http import PacedHttp
from poweron.core.domain.models import KYIV, Address, Building, City, DaySchedule, Street
from poweron.core.domain.providers import HOE, plain_subqueue, scoped_subqueue
from poweron.core.domain.schedule import day_slots
from poweron.core.domain.text import LATIN_LOOKALIKES, TYPE_PREFIX
from poweron.core.ports import ApiSchemaError, SourceError, SourceUnavailable

SITE = "https://hoe.com.ua"
# Shows the current day's post; only read to check that the archive is not missing it.
SCHEDULE_PAGE = f"{SITE}/page/pogodinni-vidkljuchennja"
ARCHIVE = f"{SITE}/page/arhiv-grafikiv-pogodinnih-vidkljuchen-{{year}}"
CACHE_SECONDS = 60.0
# The site's lookup answers its 404 page to anything that does not look like jQuery.
AJAX = {"X-Requested-With": "XMLHttpRequest"}
LATIN = str.maketrans(LATIN_LOOKALIKES)
APOSTROPHES = re.compile(r"['ʼ’‘`]")
# «м. Кам'янець-Подільський (Кам’янець-Подільська громада)»
SETTLEMENT = re.compile(r"(?P<name>.+?)\s*\((?P<hromada>[^()]+)\)")
QUEUES = re.compile(r"підчерги:\s*<strong>([^<]*)</strong>")
NO_QUEUE = {"-", ""}

logger = logging.getLogger(__name__)


class _Named(BaseModel):
    id: int
    text: str


_NAMED = TypeAdapter(list[_Named])
# Day → subqueue → (when its codes were first seen, 48 slot codes).
type _Days = dict[date, dict[str, tuple[datetime, str]]]
_HOUSES = TypeAdapter(list[str])


class HoeClient:
    """Khmelnytskoblenergo's site: schedules from its daily posts, the «Перевірити чергу» lookup."""

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
        self._current: tuple[float, date, _Days] | None = None
        self._failure: tuple[float, SourceError] | None = None
        # The posts carry no publication time: a subqueue's day dates from when it was first seen.
        # ponytail: in memory, so a restart dates every current day anew.
        self._seen: dict[tuple[date, str], tuple[str, datetime]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """The address is ignored: one post holds every subqueue."""
        subqueue = plain_subqueue(cherg_gpv)
        if subqueue not in SUBQUEUES:
            return []
        return [
            DaySchedule(cherg_gpv=cherg_gpv, day=day, created_at=seen_at, slots=day_slots(codes))
            for day, subqueues in sorted((await self._current_days()).items())
            for seen_at, codes in [subqueues[subqueue]]
        ]

    async def search_cities(self, query: str) -> list[City]:
        cities = []
        for item in await self._search("settlements/", query):
            match = SETTLEMENT.fullmatch(item.text)
            name, hromada = (match["name"], match["hromada"]) if match else (item.text, None)
            cities.append(City(id=item.id, name=name, otg_name=hromada))
        return cities

    async def search_streets(self, city_id: int, query: str) -> list[Street]:
        return [
            Street(id=item.id, name=item.text)
            for item in await self._search(f"streets/{city_id}", query)
        ]

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        response = await self._http.get(f"{SITE}/houses/{street_id}", {}, AJAX, json=True)
        names = _validate(_HOUSES, response.json(), "houses")
        return [Building(id=_stable_id(name), name=name, cherg_gpv=None) for name in names]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        response = await self._http.post(
            f"{SITE}/shutdown-queues", {"streetId": str(street_id), "house": building_name}, AJAX
        )
        match = QUEUES.search(response.text)
        if match is None:
            raise ApiSchemaError("hoe shutdown-queues: no subqueue line")
        value = match.group(1).strip()
        if value in NO_QUEUE:  # «-»; the empty ГАВ line next to it suggests "" may come too
            return []
        subqueues = [part.strip() for part in value.split(",")]
        if not set(subqueues) <= SUBQUEUES:
            raise ApiSchemaError(f"hoe shutdown-queues: unknown subqueue {value[:40]!r}")
        return sorted(scoped_subqueue(HOE, subqueue) for subqueue in subqueues)

    async def _search(self, path: str, query: str) -> list[_Named]:
        term = _search_term(query)
        if not term:
            return []
        response = await self._http.get(f"{SITE}/{path}", {"term": term}, AJAX, json=True)
        return _validate(_NAMED, response.json(), path)

    async def _current_days(self) -> _Days:
        today = self._now().astimezone(KYIV).date()
        async with self._cache_lock:
            if self._current:
                expires_at, cached_day, days = self._current
                if cached_day == today and self._monotonic() < expires_at:
                    return days
            # One failed pass is enough: the other subqueues of this poll fail at once.
            if self._failure and self._monotonic() < self._failure[0]:
                raise type(self._failure[1])(str(self._failure[1]))
            try:
                days = await self._fetch_days(today)
            except SourceError as error:
                self._failure = (self._monotonic() + CACHE_SECONDS, error)
                raise
            self._failure = None
            self._current = (self._monotonic() + CACHE_SECONDS, today, days)
            return days

    async def _fetch_days(self, today: date) -> _Days:
        tomorrow = today + timedelta(days=1)
        entries = await self._archive(today.year)
        if tomorrow.year != today.year:
            entries |= await self._archive(tomorrow.year, missing_ok=True)
        # The archive is the only index of days: a day the schedule page shows but the archive
        # lacks means the archive changed, not that nothing was published.
        shown = announced_day((await self._http.get(SCHEDULE_PAGE, {}, {})).text)
        days: _Days = {}
        for day in (today, tomorrow):
            links = entries.get(day)
            if not links:
                if shown == (day.day, day.month):
                    raise ApiSchemaError(f"hoe: the schedule page shows {day}, the archive not")
                continue  # not published: today unknown, the last version stays
            try:
                if len(links) > 1 or "/post/" not in links[0]:
                    raise ApiSchemaError(f"hoe archive {day}: {len(links)} entries, not one post")
                page = (await self._http.get(links[0], {}, {})).text
                if announced_day(page) != (day.day, day.month):
                    raise ApiSchemaError(f"hoe archive {day}: its post is about another day")
                subqueues = parse_post(page)
            except ApiSchemaError as error:
                if day == today:
                    raise  # a broken or cancelled today must reach the admin
                # A half-edited tomorrow must not hide today; it is read again next poll.
                logger.error("hoe schedule for %s skipped: %s", day, error)
                continue
            days[day] = {
                subqueue: (self._seen_at(day, subqueue, codes), codes)
                for subqueue, codes in subqueues.items()
            }
        self._seen = {key: seen for key, seen in self._seen.items() if key[0] >= today}
        return days

    async def _archive(self, year: int, *, missing_ok: bool = False) -> dict[date, list[str]]:
        """A year's archive page; next year's may not exist yet on 31.12."""
        url = ARCHIVE.format(year=year)
        try:
            return parse_archive((await self._http.get(url, {}, {})).text, url)
        except SourceUnavailable:
            if missing_ok:
                return {}
            raise

    def _seen_at(self, day: date, subqueue: str, codes: str) -> datetime:
        seen = self._seen.get((day, subqueue))
        if seen is None or seen[0] != codes:
            seen = (codes, self._now().astimezone(KYIV))
            self._seen[(day, subqueue)] = seen
        return seen[1]


def _search_term(query: str) -> str:
    """The site matches a plain substring of the bare name, with its own apostrophe only."""
    text = TYPE_PREFIX.sub("", " ".join(query.casefold().translate(LATIN).split()))
    return max(APOSTROPHES.split(text), key=len).strip()


def _validate[Model](adapter: TypeAdapter[Model], data: object, endpoint: str) -> Model:
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise ApiSchemaError.from_validation(f"hoe {endpoint}", error) from None


def _stable_id(building_name: str) -> int:
    """Houses carry no id; the name gives one that survives a refetch."""
    return zlib.crc32(building_name.encode()) & 0x7FFFFFFF

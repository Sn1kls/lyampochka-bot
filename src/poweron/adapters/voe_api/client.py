import asyncio
import logging
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta
from importlib.metadata import version
from typing import Annotated, Any

import httpx
from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, ValidationError

from poweron.adapters.paced_http import PacedHttp
from poweron.adapters.voe_api.image import SUBQUEUES, decode_schedule
from poweron.core.domain.models import KYIV, Address, DaySchedule
from poweron.core.domain.providers import plain_subqueue
from poweron.core.domain.schedule import day_slots
from poweron.core.ports import ApiSchemaError, SourceError

MAX_PAGES = 10
MAX_IMAGE_BYTES = 5_000_000
LIST_CACHE_SECONDS = 60.0
IMAGES_KEPT = 8

logger = logging.getLogger(__name__)


class _Image(BaseModel):
    contentUrl: Annotated[str, StringConstraints(pattern=r"^/media/[\w./-]+$")]


class _Item(BaseModel):
    dateGraph: AwareDatetime
    dateCreate: AwareDatetime
    imageUrl: _Image


class _Page(BaseModel):
    members: list[_Item] = Field(alias="hydra:member")
    total: int = Field(alias="hydra:totalItems")


class VoeClient:
    def __init__(
        self,
        base_url: str,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(KYIV),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._http = PacedHttp(
            httpx.AsyncClient(
                base_url=base_url,
                headers={"User-Agent": f"poweron-bot/{version('poweron')} (personal use)"},
                timeout=30,
            ),
            monotonic,
            sleep,
        )
        self._now = now
        self._monotonic = monotonic
        self._cache_lock = asyncio.Lock()
        self._current: tuple[float, date, dict[date, tuple[datetime, dict[str, str]]]] | None = None
        self._images: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._failure: tuple[float, SourceError] | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        """The address is ignored: one image holds every subqueue."""
        plain = plain_subqueue(cherg_gpv)
        if plain not in SUBQUEUES:
            return []
        current = await self._current_grids()
        return [
            DaySchedule(
                cherg_gpv=cherg_gpv,
                day=day,
                created_at=created_at,
                slots=day_slots(grid[plain]),
            )
            for day, (created_at, grid) in sorted(current.items())
        ]

    async def _current_grids(self) -> dict[date, tuple[datetime, dict[str, str]]]:
        today = self._now().astimezone(KYIV).date()
        async with self._cache_lock:
            if self._current:
                expires_at, cached_day, grids = self._current
                if cached_day == today and self._monotonic() < expires_at:
                    return grids
            # One failed pass is enough: the other subqueues of this poll fail at once
            # instead of each retrying for ~10 s under the request lock.
            if self._failure and self._monotonic() < self._failure[0]:
                raise type(self._failure[1])(str(self._failure[1]))
            try:
                grids = await self._fetch_grids(today)
            except SourceError as error:
                self._failure = (self._monotonic() + LIST_CACHE_SECONDS, error)
                raise
            self._failure = None
            self._current = (self._monotonic() + LIST_CACHE_SECONDS, today, grids)
            return grids

    async def _fetch_grids(self, today: date) -> dict[date, tuple[datetime, dict[str, str]]]:
        newest: dict[date, _Item] = {}
        tomorrow = today + timedelta(days=1)
        for item in await self._items(today, tomorrow):
            day = item.dateGraph.date()
            if day not in (today, tomorrow):  # the server ignores a filter it cannot parse
                continue
            if day not in newest or item.dateCreate > newest[day].dateCreate:
                newest[day] = item
        return {
            day: (item.dateCreate, await self._grid(item.imageUrl.contentUrl))
            for day, item in newest.items()
        }

    async def _items(self, first_day: date, last_day: date) -> list[_Item]:
        params: dict[str, Any] = {
            "dateGraph[after]": f"{first_day}T00:00:00+02:00Z",
            "dateGraph[before]": f"{last_day}T00:00:00+02:00Z",
        }
        items: list[_Item] = []
        for page_number in range(1, MAX_PAGES + 1):
            response = await self._http.get(
                "/api/archive_gpv_graphs",
                params | {"page": page_number},
                {"Accept": "application/ld+json"},
                json=True,
            )
            try:
                page = _Page.model_validate(response.json())
            except ValidationError as error:
                raise ApiSchemaError.from_validation("archive_gpv_graphs", error) from None
            items += page.members
            if not page.members or len(items) >= page.total:
                return items
        logger.warning("voe archive cut at %s pages", MAX_PAGES)
        return items

    async def _grid(self, content_url: str) -> dict[str, str]:
        if content_url in self._images:
            self._images.move_to_end(content_url)
            return self._images[content_url]
        response = await self._http.get(content_url, {}, {"Accept": "image/png"})
        if len(response.content) > MAX_IMAGE_BYTES:
            raise ApiSchemaError(f"{content_url}: image too large")
        grid = await asyncio.to_thread(decode_schedule, response.content)
        self._images[content_url] = grid
        while len(self._images) > IMAGES_KEPT:
            self._images.popitem(last=False)
        return grid

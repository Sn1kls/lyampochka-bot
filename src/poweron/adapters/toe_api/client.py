import asyncio
import base64
import logging
import random
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from poweron.adapters.toe_api.models import (
    BUILDING_GROUPS_ADAPTER,
    BUILDINGS_ADAPTER,
    CITIES_ADAPTER,
    PLANNED_WORK_ADAPTER,
    SCHEDULES_ADAPTER,
    STREETS_ADAPTER,
    RawPlannedWork,
    subqueue,
)
from poweron.core.domain.models import (
    KYIV,
    Address,
    Building,
    City,
    DaySchedule,
    PlannedWork,
    Street,
)
from poweron.core.ports import ApiSchemaError, SourceUnavailable

ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
MIN_REQUEST_INTERVAL = 1.0
MAX_RETRY_AFTER = 60.0
MAX_PLANNED_WORK_PAGES = 10
MAX_REASON_LENGTH = 300
BREAKER_THRESHOLD = 3
BREAKER_FIRST_PAUSE = 60.0
BREAKER_MAX_PAUSE = 3600.0
MAX_DOUBLINGS = 10

logger = logging.getLogger(__name__)


class ToeClient:
    def __init__(
        self,
        base_url: str,
        *,
        contact: str,
        now: Callable[[], datetime] = lambda: datetime.now(KYIV),
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        user_agent = f"poweron-bot/{version('poweron')} (personal use; contact: {contact})"
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"Accept": "application/json", "User-Agent": user_agent},
            timeout=30,
        )
        self._now = now
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_request_at = float("-inf")
        self._consecutive_failures = 0
        self._paused_until = float("-inf")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        requested = subqueue(cherg_gpv)
        if requested is None:
            return []
        # The server reads the subqueue from X-debug-key only, but the CDN caches by URL:
        # `time` must always match the key, or the cached entry for this address is poisoned.
        address_path = f"{address.city_id}/{address.street_id}/{address.building_name}"
        now = self._now()
        today = now.astimezone(KYIV).date()
        params = {
            "after": f"{today - timedelta(days=1)}T12:00:00+00:00",
            # A new time of day on every poll gives a new URL and bypasses the 2 h CDN cache.
            "before": f"{today + timedelta(days=1)}T{now.astimezone(KYIV):%H:%M:%S}+00:00",
            "group": cherg_gpv,
            "time": address_path.replace("/", ""),
        }
        headers = {"X-debug-key": base64.b64encode(address_path.encode()).decode()}
        response = await self._get("a_gpv_g", params, headers)
        schedules = [
            DaySchedule(
                cherg_gpv=requested,
                day=graph.dateGraph.date(),
                created_at=graph.dateCreate,
                slots=group.times,
            )
            for graph in _validate(SCHEDULES_ADAPTER, response).member or []
            for key, group in graph.dataJson.items()
            if subqueue(key) == requested
        ]
        return sorted(schedules, key=lambda schedule: schedule.day)

    async def cities(self) -> list[City]:
        response = await self._get("pw_cities", {"pagination": "false"})
        return [
            City(id=city.id, name=city.name, otg_name=city.otg.name if city.otg else None)
            for city in _validate(CITIES_ADAPTER, _members(response))
        ]

    async def streets(self, city_id: int) -> list[Street]:
        response = await self._get("pw_streets", {"pagination": "false", "city.id": city_id})
        return [
            Street(id=street.id, name=street.name)
            for street in _validate(STREETS_ADAPTER, _members(response))
        ]

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        params = {"cityId": city_id, "streetId": street_id}
        response = await self._get("pw-accounts/building-names", params)
        return [
            Building(id=building.id, name=building.buildingName, cherg_gpv=building.chergGpv)
            for building in _validate(BUILDINGS_ADAPTER, response).buildingNames
        ]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        params = {"cityId": city_id, "streetId": street_id, "buildingNames": building_name}
        response = await self._get("pw-accounts/building-groups", params)
        groups = _validate(BUILDING_GROUPS_ADAPTER, response).buildingGroups
        return list(dict.fromkeys(q for group in groups if (q := subqueue(group.chergGpv))))

    async def planned_works(
        self, city_id: int, street_id: int, after: datetime
    ) -> list[PlannedWork]:
        params: dict[str, Any] = {
            "city.id": city_id,
            "street.id": street_id,
            "datePlanIn[after]": f"{after.astimezone(KYIV):%Y-%m-%dT%H:%M:%S}",
        }
        works: list[PlannedWork] = []
        for page in range(1, MAX_PLANNED_WORK_PAGES + 1):
            response = await self._get("pw_accident_planeds", params | {"page": page})
            items = _members(response)
            if not isinstance(items, list):
                raise ApiSchemaError("pw_accident_planeds: not a list")
            if not items:
                return works
            raw_works = [raw for item in items if (raw := _raw_planned_work(item))]
            if not raw_works:
                raise ApiSchemaError("pw_accident_planeds: no item matches the expected format")
            works += [work for raw in raw_works if (work := _planned_work(raw, street_id))]
        logger.warning("planned works of street %s cut at %s pages", street_id, page)
        return works

    async def _get(
        self, path: str, params: dict[str, Any], headers: dict[str, str] | None = None
    ) -> Any:
        async with self._lock:
            if self._monotonic() < self._paused_until:
                raise SourceUnavailable(f"{path}: paused after repeated failures")
            try:
                response = await self._request(path, params, headers)
            except SourceUnavailable:
                self._record_failure()
                raise
            except ApiSchemaError:
                self._consecutive_failures = 0  # the API answered, so it is up
                raise
            self._consecutive_failures = 0
            return response

    def _record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= BREAKER_THRESHOLD:
            doublings = min(self._consecutive_failures - BREAKER_THRESHOLD, MAX_DOUBLINGS)
            pause = min(BREAKER_FIRST_PAUSE * 2**doublings, BREAKER_MAX_PAUSE)
            self._paused_until = self._monotonic() + pause
            logger.warning(
                "toe api paused for %.0f s after %s failed requests in a row",
                pause,
                self._consecutive_failures,
            )

    async def _request(
        self, path: str, params: dict[str, Any], headers: dict[str, str] | None
    ) -> Any:
        for attempt in range(1, ATTEMPTS + 1):
            wait = self._last_request_at + MIN_REQUEST_INTERVAL - self._monotonic()
            if wait > 0:
                await self._sleep(wait)
            try:
                response = await self._http.get(path, params=params, headers=headers)
            except httpx.RequestError as error:
                failure = f"{type(error).__name__}: {error}"
                delay = _backoff(attempt)
            else:
                if response.status_code == 200:
                    return _json(path, response)
                if response.status_code not in RETRY_STATUSES:
                    raise SourceUnavailable(f"{path}: HTTP {response.status_code}")
                failure = f"HTTP {response.status_code}"
                delay = _retry_after(response) or _backoff(attempt)
            finally:
                self._last_request_at = self._monotonic()
            if attempt < ATTEMPTS:
                await self._sleep(delay)
        raise SourceUnavailable(f"{path}: {failure} after {ATTEMPTS} attempts")


def _raw_planned_work(item: Any) -> RawPlannedWork | None:
    try:
        return PLANNED_WORK_ADAPTER.validate_python(item)
    except ValidationError as error:
        logger.warning("skipped a planned work with %s format errors", error.error_count())
        return None


def _planned_work(raw: RawPlannedWork, street_id: int) -> PlannedWork | None:
    """None for another street or when the API breaks the wall-clock time assumption."""
    if raw.street.id != street_id:
        return None
    if raw.dateEvent.utcoffset() or raw.datePlanIn.utcoffset():
        logger.warning("skipped planned work %s: the API now sends real time offsets", raw.id)
        return None
    reason = " ".join((raw.koment or "").split())
    if len(reason) > MAX_REASON_LENGTH:
        reason = reason[: MAX_REASON_LENGTH - 1].rstrip() + "…"
    return PlannedWork(
        id=raw.id,
        street_id=raw.street.id,
        starts_at=_kyiv_wall_clock(raw.dateEvent),
        ends_at=_kyiv_wall_clock(raw.datePlanIn),
        reason=reason,
        building_names=tuple(
            name for part in (raw.buildingNames or "").split(",") if (name := part.strip())
        ),
    )


def _kyiv_wall_clock(labelled: datetime) -> datetime:
    """The site labels Kyiv wall-clock time as +00:00; keep the clock fields, fix the zone."""
    return labelled.replace(tzinfo=KYIV).astimezone(UTC)


def _backoff(attempt: int) -> float:
    return float(2**attempt) + random.uniform(0, 1)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return min(float(value), MAX_RETRY_AFTER) if value.isdigit() else None


def _json(path: str, response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise ApiSchemaError(f"{path}: not JSON") from error


def _members(response: Any) -> Any:
    if isinstance(response, dict) and "hydra:member" in response:
        return response["hydra:member"]
    return response


def _validate[Model](adapter: TypeAdapter[Model], data: Any) -> Model:
    try:
        return adapter.validate_python(data)
    except ValidationError as error:
        raise ApiSchemaError(str(error)) from error

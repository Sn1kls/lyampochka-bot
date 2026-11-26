import asyncio
import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from poweron.core.domain.models import (
    Address,
    CurrentOutage,
    OutageKind,
    PlannedWork,
    Subscription,
)
from poweron.core.ports import CurrentOutageSource, SourceError

CACHE_TTL = timedelta(minutes=5)
# The timeout cuts the client's retries short, so its breaker never opens for these endpoints.
FAILURE_TTL = timedelta(minutes=1)
TIMEOUT_SEC = 3.0

logger = logging.getLogger(__name__)


class CurrentOutages:
    """The outage the oblenergo lists on a subscription's building right now; an emergency wins.

    Best effort, asked while a user waits for an answer: a slow or broken source shows nothing.
    """

    def __init__(
        self, sources: Mapping[str, CurrentOutageSource], timeout: float = TIMEOUT_SEC
    ) -> None:
        self._sources = sources
        self._timeout = timeout
        # (region, kind, city id, street id) → (expires at, works)
        self._cache: dict[tuple[str, OutageKind, int, int], tuple[datetime, list[PlannedWork]]] = {}

    async def current(self, subscription: Subscription, now: datetime) -> CurrentOutage | None:
        source = self._sources.get(subscription.provider)
        if source is None:
            return None
        address = subscription.address
        # One budget for both requests, so the user never waits longer than the timeout.
        deadline = asyncio.get_running_loop().time() + self._timeout
        for kind in (OutageKind.EMERGENCY, OutageKind.PLANNED):
            key = (subscription.provider, kind, address.city_id, address.street_id)
            for work in await self._works(source, key, address, now, deadline):
                # The oblenergo leaves some outages open for days after their planned end.
                if work.starts_at <= now < work.ends_at and work.affects(address.building_name):
                    return CurrentOutage(kind, work)
        return None

    async def _works(
        self,
        source: CurrentOutageSource,
        key: tuple[str, OutageKind, int, int],
        address: Address,
        now: datetime,
        deadline: float,
    ) -> list[PlannedWork]:
        cached = self._cache.get(key)
        if cached and now < cached[0]:
            return cached[1]
        kind = key[1]
        try:
            async with asyncio.timeout_at(deadline):
                if kind is OutageKind.EMERGENCY:
                    works = await source.emergency_outages(address.city_id, address.street_id)
                else:
                    works = await source.planned_works(address.city_id, address.street_id, now)
        except (SourceError, TimeoutError) as error:
            logger.warning("%s outages of street %s: %r", kind, address.street_id, error)
            works, lifetime = [], FAILURE_TTL
        else:
            lifetime = CACHE_TTL
        self._cache[key] = (now + lifetime, works)
        return works

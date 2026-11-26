import asyncio
import logging
from datetime import datetime, timedelta

from poweron.core.domain.models import PlannedWork, Subscription
from poweron.core.domain.providers import TOE
from poweron.core.ports import EmergencyOutageSource, SourceError

CACHE_TTL = timedelta(minutes=5)
# The timeout cuts the client's retries short, so its breaker never opens for this endpoint.
FAILURE_TTL = timedelta(minutes=1)
TIMEOUT_SEC = 3.0

logger = logging.getLogger(__name__)


class EmergencyOutages:
    """The emergency outage the oblenergo lists on a subscription's building right now.

    Best effort, asked while a user waits for an answer: a slow or broken source shows nothing.
    """

    def __init__(self, source: EmergencyOutageSource, timeout: float = TIMEOUT_SEC) -> None:
        self._source = source
        self._timeout = timeout
        self._cache: dict[tuple[int, int], tuple[datetime, list[PlannedWork]]] = {}  # expires at

    async def current(self, subscription: Subscription, now: datetime) -> PlannedWork | None:
        if subscription.provider != TOE:  # the only region whose API lists them
            return None
        address = subscription.address
        for outage in await self._outages(address.city_id, address.street_id, now):
            # The oblenergo leaves some outages open for days after their planned end.
            if outage.starts_at <= now < outage.ends_at and outage.affects(address.building_name):
                return outage
        return None

    async def _outages(self, city_id: int, street_id: int, now: datetime) -> list[PlannedWork]:
        cached = self._cache.get((city_id, street_id))
        if cached and now < cached[0]:
            return cached[1]
        try:
            async with asyncio.timeout(self._timeout):
                outages = await self._source.emergency_outages(city_id, street_id)
        except (SourceError, TimeoutError) as error:
            logger.warning("emergency outages of street %s: %r", street_id, error)
            outages, ttl = [], FAILURE_TTL
        else:
            ttl = CACHE_TTL
        self._cache[(city_id, street_id)] = (now + ttl, outages)
        return outages

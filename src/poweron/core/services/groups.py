import logging
from collections import defaultdict
from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, OutboxMessage, Subscription
from poweron.core.ports import CatalogSource, Repository, SourceError

logger = logging.getLogger(__name__)

RECHECK_AFTER = timedelta(hours=24)


class GroupResolver:
    """Daily re-check that a building is still in the same subqueues.

    Payload of `subqueues_changed`: {"subscription_id": int, "label": str,
    "previous": [str], "current": [str], "tracked": [str]}.
    """

    def __init__(self, repository: Repository, source: CatalogSource) -> None:
        self._repository = repository
        self._source = source

    async def resolve(self, now: datetime) -> None:
        by_building: dict[tuple[int, int, str], list[Subscription]] = defaultdict(list)
        for subscription in await self._repository.stale_subscriptions(now - RECHECK_AFTER):
            address = subscription.address
            key = (address.city_id, address.street_id, address.building_name)
            by_building[key].append(subscription)
        for (city_id, street_id, building_name), subscribers in by_building.items():
            try:
                found = await self._source.building_subqueues(city_id, street_id, building_name)
            except SourceError as error:
                logger.warning("subqueue re-check failed for a building: %s", error)
                continue
            for subscription in subscribers:
                await self._apply(subscription, set(found), now)

    async def _apply(self, subscription: Subscription, current: set[str], now: datetime) -> None:
        previous = set(subscription.subqueues)
        if not current:
            logger.warning(
                "subscription %s: building has no subqueues now; keeping", subscription.id
            )
        if not current or current == previous:
            await self._repository.mark_checked(subscription.id, now)
            return
        tracked = set(subscription.tracked_subqueues)
        tracked = current if tracked == previous else tracked & current
        tracked = tracked or current
        message = OutboxMessage(
            user_id=subscription.user_id,
            kind=MessageKind.SUBQUEUES_CHANGED,
            payload={
                "subscription_id": subscription.id,
                "label": subscription.label,
                "previous": sorted(previous),
                "current": sorted(current),
                "tracked": sorted(tracked),
            },
            dedupe_key=f"subqueues:{subscription.id}:{','.join(sorted(current))}:{now.isoformat()}",
        )
        await self._repository.replace_subqueues(
            subscription.id, sorted(current), sorted(tracked), now, [message]
        )

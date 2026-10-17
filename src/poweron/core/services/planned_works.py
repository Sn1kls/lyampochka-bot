import logging
from collections import defaultdict
from datetime import datetime

from poweron.core.domain.models import MessageKind, OutboxMessage, PlannedWork, Subscription
from poweron.core.ports import PlannedWorkSource, Repository
from poweron.core.services.catalog import normalise

logger = logging.getLogger(__name__)


class PlannedWorks:
    """Announces planned works on a subscription's street that list its building.

    Payload of `planned_work`: {"subscription_id": int, "label": str, "starts_at": ISO,
    "ends_at": ISO, "reason": str (may be empty)}.
    """

    def __init__(self, repository: Repository, source: PlannedWorkSource) -> None:
        self._repository = repository
        self._source = source

    async def check(self, now: datetime) -> None:
        by_street: dict[tuple[int, int], list[Subscription]] = defaultdict(list)
        for subscription in await self._repository.all_subscriptions():
            if subscription.notify_on_update:
                address = subscription.address
                by_street[(address.city_id, address.street_id)].append(subscription)
        for (city_id, street_id), subscribers in by_street.items():
            try:
                works = await self._source.planned_works(city_id, street_id, now)
                await self._repository.enqueue_messages(
                    [
                        _message(subscription, work)
                        for subscription in subscribers
                        for work in works
                        if _affects(work, subscription)
                    ]
                )
            except Exception:
                logger.exception("planned works check failed for street %s", street_id)


def _affects(work: PlannedWork, subscription: Subscription) -> bool:
    if not work.building_names:
        return True
    listed = {normalise(name) for name in work.building_names}
    return normalise(subscription.address.building_name) in listed


def _message(subscription: Subscription, work: PlannedWork) -> OutboxMessage:
    starts_at = work.starts_at.isoformat()
    ends_at = work.ends_at.isoformat()
    return OutboxMessage(
        user_id=subscription.user_id,
        kind=MessageKind.PLANNED_WORK,
        payload={
            "subscription_id": subscription.id,
            "label": subscription.label,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "reason": work.reason,
        },
        dedupe_key=f"planned:{subscription.id}:{work.id}:{starts_at}:{ends_at}",
    )

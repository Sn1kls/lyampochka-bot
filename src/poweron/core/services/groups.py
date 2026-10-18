import logging
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, OutboxMessage, Subscription
from poweron.core.ports import CatalogSource, Repository, SourceError
from poweron.core.services.alerts import Alerts, report_source_error
from poweron.core.services.polling import never_stop

logger = logging.getLogger(__name__)

RECHECK_AFTER = timedelta(hours=24)


class SubqueueChecker:
    """Daily re-check that a building is still in the same subqueues.

    Payload of `subqueues_changed`: {"subscription_id": int, "label": str,
    "previous": [str], "current": [str] (empty: the building left the schedule),
    "tracked": [str]}.
    """

    def __init__(
        self, repository: Repository, source: CatalogSource, alerts: Alerts | None = None
    ) -> None:
        self._repository = repository
        self._source = source
        self._alerts = alerts

    async def check(self, now: datetime, should_stop: Callable[[], bool] = never_stop) -> None:
        by_building: dict[tuple[int, int, str], list[Subscription]] = defaultdict(list)
        for subscription in await self._repository.stale_subscriptions(now - RECHECK_AFTER):
            address = subscription.address
            key = (address.city_id, address.street_id, address.building_name)
            by_building[key].append(subscription)
        changed = 0
        for (city_id, street_id, building_name), subscribers in by_building.items():
            if should_stop():
                break
            try:
                found = await self._source.building_subqueues(city_id, street_id, building_name)
            except SourceError as error:
                logger.warning("subqueue re-check failed for a building: %s", error)
                await report_source_error(self._alerts, error, now)
                continue
            for subscription in subscribers:
                try:
                    changed += await self._apply(subscription, set(found), now)
                except Exception:
                    logger.exception(
                        "subqueue re-check failed for subscription %s", subscription.id
                    )
        if by_building:
            logger.info("subqueue_check buildings=%s changed=%s", len(by_building), changed)

    async def _apply(self, subscription: Subscription, current: set[str], now: datetime) -> bool:
        """Returns whether the stored queues differ from the current ones."""
        previous = set(subscription.subqueues)
        tracked = set(subscription.tracked_subqueues)
        if current == previous:
            await self._repository.mark_checked(subscription.id, now)
            return False
        if not current:
            # An empty answer may be a data glitch, so the stored queues stay.
            logger.warning("subscription %s: building has no subqueues now", subscription.id)
            await self._repository.enqueue_messages(
                [_changed_message(subscription, previous, current, tracked)]
            )
            await self._repository.mark_checked(subscription.id, now)
            return True
        tracked = _tracked_after_change(previous, tracked, current)
        await self._repository.replace_subqueues(
            subscription.id,
            sorted(current),
            sorted(tracked),
            now,
            [_changed_message(subscription, previous, current, tracked)],
        )
        return True


def _tracked_after_change(previous: set[str], tracked: set[str], current: set[str]) -> set[str]:
    """Someone who tracked every queue follows the new ones; otherwise keep their picks."""
    kept = current if tracked == previous else tracked & current
    return kept or current


def _changed_message(
    subscription: Subscription, previous: set[str], current: set[str], tracked: set[str]
) -> OutboxMessage:
    return OutboxMessage(
        user_id=subscription.user_id,
        kind=MessageKind.SUBQUEUES_CHANGED,
        payload={
            "subscription_id": subscription.id,
            "label": subscription.label,
            "previous": sorted(previous),
            "current": sorted(current),
            "tracked": sorted(tracked),
        },
        dedupe_key=(
            f"subqueues:{subscription.id}:{','.join(sorted(previous))}>{','.join(sorted(current))}"
        ),
    )

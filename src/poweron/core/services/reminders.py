import logging
import math
from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, NextEvent, OutboxMessage, Subscription
from poweron.core.ports import Repository
from poweron.core.services.schedules import Schedules

logger = logging.getLogger(__name__)


class Reminders:
    """Queues "power goes off / comes back in N minutes" messages.

    Payload of `reminder_off` / `reminder_on`: {"subscription_id": int, "label": str,
    "cherg_gpv": str, "queue_count": int (tracked queues), "minutes": int (left until
    `earliest`, rounded up), "earliest": ISO datetime, "latest": ISO datetime | None}
    — the event window of NextEvent.
    """

    def __init__(self, repository: Repository, schedules: Schedules) -> None:
        self._repository = repository
        self._schedules = schedules

    async def tick(self, now: datetime) -> None:
        """Remind once per event, from `earliest - setting` until the event starts."""
        events_by_queue: dict[str, list[NextEvent]] = {}
        messages = []
        for subscription in await self._repository.all_subscriptions():
            try:
                for cherg_gpv in subscription.tracked_subqueues:
                    if cherg_gpv not in events_by_queue:
                        events_by_queue[cherg_gpv] = await self._schedules.queue_events(
                            cherg_gpv, now
                        )
                    messages += _due_messages(
                        subscription, cherg_gpv, events_by_queue[cherg_gpv], now
                    )
            except Exception:
                logger.exception("reminders failed for subscription %s", subscription.id)
        await self._repository.enqueue_messages(messages)


def _due_messages(
    subscription: Subscription, cherg_gpv: str, events: list[NextEvent], now: datetime
) -> list[OutboxMessage]:
    messages = []
    for event in events:
        kind = MessageKind.REMINDER_ON if event.power_on else MessageKind.REMINDER_OFF
        setting = (
            subscription.remind_before_on_min
            if event.power_on
            else subscription.remind_before_off_min
        )
        if setting > 0 and event.earliest - timedelta(minutes=setting) <= now < event.earliest:
            messages.append(_message(subscription, cherg_gpv, event, kind, now))
    return messages


def _message(
    subscription: Subscription,
    cherg_gpv: str,
    event: NextEvent,
    kind: MessageKind,
    now: datetime,
) -> OutboxMessage:
    earliest = event.earliest.isoformat()
    return OutboxMessage(
        user_id=subscription.user_id,
        kind=kind,
        payload={
            "subscription_id": subscription.id,
            "label": subscription.label,
            "cherg_gpv": cherg_gpv,
            "queue_count": len(subscription.tracked_subqueues),
            "minutes": math.ceil((event.earliest - now).total_seconds() / 60),
            "earliest": earliest,
            "latest": None if event.latest is None else event.latest.isoformat(),
        },
        dedupe_key=f"remind:{subscription.id}:{cherg_gpv}:{earliest}:{kind.value}",
    )

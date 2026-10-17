from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, NextEvent, OutboxMessage, Subscription
from poweron.core.ports import Repository
from poweron.core.services.schedules import Schedules


class Reminders:
    """Queues "power goes off / comes back in N minutes" messages.

    Payload of `reminder_off` / `reminder_on`: {"subscription_id": int, "label": str,
    "cherg_gpv": str, "queue_count": int (tracked queues), "minutes": int,
    "earliest": ISO datetime, "latest": ISO datetime | None} — the event window of NextEvent.
    """

    def __init__(self, repository: Repository) -> None:
        self._repository = repository
        self._schedules = Schedules(repository)

    async def tick(self, now: datetime) -> None:
        """Remind once per event, from `earliest - minutes` until the event starts."""
        messages = []
        for subscription in await self._repository.all_subscriptions():
            for cherg_gpv, event in await self._schedules.events(subscription, now):
                minutes = (
                    subscription.remind_before_on_min
                    if event.power_on
                    else subscription.remind_before_off_min
                )
                if (
                    minutes > 0
                    and event.earliest - timedelta(minutes=minutes) <= now < event.earliest
                ):
                    messages.append(_message(subscription, cherg_gpv, event, minutes))
        await self._repository.enqueue_messages(messages)


def _message(
    subscription: Subscription, cherg_gpv: str, event: NextEvent, minutes: int
) -> OutboxMessage:
    earliest = event.earliest.isoformat()
    direction = "on" if event.power_on else "off"
    return OutboxMessage(
        user_id=subscription.user_id,
        kind=MessageKind.REMINDER_ON if event.power_on else MessageKind.REMINDER_OFF,
        payload={
            "subscription_id": subscription.id,
            "label": subscription.label,
            "cherg_gpv": cherg_gpv,
            "queue_count": len(subscription.tracked_subqueues),
            "minutes": minutes,
            "earliest": earliest,
            "latest": None if event.latest is None else event.latest.isoformat(),
        },
        dedupe_key=f"remind:{subscription.id}:{cherg_gpv}:{earliest}:{direction}",
    )

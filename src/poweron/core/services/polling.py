import logging
from collections import defaultdict
from datetime import datetime

from poweron.core.domain.diff import ScheduleChange, data_hash, schedule_change
from poweron.core.domain.models import (
    DaySchedule,
    MessageKind,
    OutboxMessage,
    ScheduleVersion,
    Subscription,
)
from poweron.core.ports import Repository, ScheduleSource, SourceError

logger = logging.getLogger(__name__)


class Polling:
    def __init__(self, repository: Repository, source: ScheduleSource) -> None:
        self._repository = repository
        self._source = source

    async def poll(self, now: datetime) -> None:
        """Fetch every subscribed subqueue once and store new versions with their messages."""
        await self._poll_each(await self._by_subqueue(), now)

    async def poll_new(self, now: datetime) -> None:
        """Fetch only the subscribed subqueues that have no stored version yet."""
        never_polled = {
            cherg_gpv: subscribers
            for cherg_gpv, subscribers in (await self._by_subqueue()).items()
            if await self._repository.last_polled_at(cherg_gpv) is None
        }
        await self._poll_each(never_polled, now)

    async def _by_subqueue(self) -> dict[str, list[Subscription]]:
        """Every queue of a building is fetched, so that the untracked ones can be viewed too."""
        by_subqueue: dict[str, list[Subscription]] = defaultdict(list)
        for subscription in await self._repository.all_subscriptions():
            for cherg_gpv in subscription.subqueues:
                by_subqueue[cherg_gpv].append(subscription)
        return by_subqueue

    async def _poll_each(self, by_subqueue: dict[str, list[Subscription]], now: datetime) -> None:
        for cherg_gpv, subscribers in by_subqueue.items():
            try:
                await self._poll_subqueue(cherg_gpv, subscribers, now)
            except SourceError as error:
                logger.warning("poll failed for subqueue %s: %s", cherg_gpv, error)
            except Exception:
                logger.exception("poll crashed for subqueue %s", cherg_gpv)

    async def _poll_subqueue(
        self, cherg_gpv: str, subscribers: list[Subscription], now: datetime
    ) -> None:
        schedules = await self._source.fetch_schedules(subscribers[0].address, cherg_gpv)
        last_polled_at = await self._repository.last_polled_at(cherg_gpv)
        # A change is news only to subscribers who already had the previous poll's data;
        # for everyone else (and on the very first poll) this poll is their first load.
        recipients = [
            subscription
            for subscription in subscribers
            if subscription.notify_on_update
            and cherg_gpv in subscription.tracked_subqueues
            and last_polled_at is not None
            and subscription.created_at <= last_polled_at
        ]
        for schedule in schedules:
            await self._store(schedule, recipients, now)

    async def _store(
        self, schedule: DaySchedule, recipients: list[Subscription], now: datetime
    ) -> None:
        digest = data_hash(schedule.slots)
        previous = await self._repository.latest_version(schedule.cherg_gpv, schedule.day)
        messages = []
        if recipients and (previous is None or previous.data_hash != digest):
            change = schedule_change(
                schedule.cherg_gpv,
                schedule.day,
                None if previous is None else previous.slots,
                schedule.slots,
            )
            if change is not None:
                base = "new" if previous is None else previous.fetched_at.isoformat()
                messages = _messages(change, recipients, f"{base}:{digest}")
        version = ScheduleVersion(
            cherg_gpv=schedule.cherg_gpv,
            day=schedule.day,
            created_at=schedule.created_at,
            data_hash=digest,
            slots=schedule.slots,
            fetched_at=now,
        )
        await self._repository.save_version(version, messages)


def _messages(
    change: ScheduleChange, recipients: list[Subscription], transition: str
) -> list[OutboxMessage]:
    payload = change.payload()
    return [
        OutboxMessage(
            user_id=subscription.user_id,
            kind=MessageKind.SCHEDULE_UPDATED,
            payload=payload
            | {
                "subscription_id": subscription.id,
                "label": subscription.label,
                "queue_count": len(subscription.tracked_subqueues),
            },
            dedupe_key=f"update:{subscription.id}:{change.cherg_gpv}:{change.day}:{transition}",
        )
        for subscription in recipients
    ]

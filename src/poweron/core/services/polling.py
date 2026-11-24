import asyncio
import logging
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta

from poweron.core.domain.diff import ScheduleChange, data_hash, schedule_change
from poweron.core.domain.models import (
    Address,
    AlertKind,
    DaySchedule,
    MessageKind,
    OutboxMessage,
    ScheduleVersion,
    Subscription,
)
from poweron.core.domain.providers import provider_of
from poweron.core.ports import Repository, ScheduleSource, SourceError
from poweron.core.services.alerts import Alerts, report_source_error
from poweron.core.services.reminders import reminder_key

logger = logging.getLogger(__name__)

NEW_SUBQUEUE_RETRY = timedelta(minutes=5)


def never_stop() -> bool:
    return False


class Polling:
    def __init__(
        self,
        repository: Repository,
        source: ScheduleSource,
        alerts: Alerts | None = None,
        *,
        stale_after: timedelta | None = None,
    ) -> None:
        """`stale_after`: alert when a subqueue keeps failing that long, whatever the source."""
        self._repository = repository
        self._source = source
        self._alerts = alerts
        self._stale_after = stale_after
        self._new_attempts: dict[str, datetime] = {}
        self._lock = asyncio.Lock()

    async def poll(self, now: datetime, should_stop: Callable[[], bool] = never_stop) -> None:
        """Fetch every subscribed subqueue once and store new versions with their messages.

        `should_stop` is checked between subqueues, so a shutdown does not wait for the whole pass.
        """
        async with self._lock:
            by_subqueue, address_counts = await self._by_subqueue()
            await self._poll_each(by_subqueue, address_counts, now, should_stop)

    async def poll_new(self, now: datetime, should_stop: Callable[[], bool] = never_stop) -> None:
        """Fetch only the subscribed subqueues that have no stored version yet, or whose last
        poll predates their newest subscriber, so someone who subscribes to a subqueue nobody
        followed for a while does not see its old schedule.

        A subqueue the source has nothing for is retried only after NEW_SUBQUEUE_RETRY,
        so a frequent caller does not hammer the API.
        """
        # Shares the lock with poll() so a subqueue is never fetched twice at once.
        async with self._lock:
            by_subqueue, address_counts = await self._by_subqueue()
            unseen = {
                cherg_gpv: subscribers
                for cherg_gpv, subscribers in by_subqueue.items()
                if now - self._new_attempts.get(cherg_gpv, datetime.min.replace(tzinfo=UTC))
                >= NEW_SUBQUEUE_RETRY
                and await self._unseen(cherg_gpv, subscribers)
            }
            self._new_attempts.update(dict.fromkeys(unseen, now))
            await self._poll_each(unseen, address_counts, now, should_stop)

    async def _unseen(self, cherg_gpv: str, subscribers: list[Subscription]) -> bool:
        if await self._repository.last_version_at(cherg_gpv) is None:
            return True
        polled_at = await self._repository.polled_at(cherg_gpv)
        newest = max(subscription.created_at for subscription in subscribers)
        return polled_at is None or polled_at < newest

    async def _by_subqueue(self) -> tuple[dict[str, list[Subscription]], Counter[int]]:
        """Subscribers per subqueue, and how many addresses each user has.

        Every queue of a building is fetched, so that the untracked ones can be viewed too.
        """
        subscriptions = await self._repository.all_subscriptions()
        by_subqueue: dict[str, list[Subscription]] = defaultdict(list)
        for subscription in subscriptions:
            for cherg_gpv in subscription.subqueues:
                by_subqueue[cherg_gpv].append(subscription)
        return by_subqueue, Counter(subscription.user_id for subscription in subscriptions)

    async def _poll_each(
        self,
        by_subqueue: dict[str, list[Subscription]],
        address_counts: Mapping[int, int],
        now: datetime,
        should_stop: Callable[[], bool],
    ) -> None:
        started = time.monotonic()
        changed = messages = 0
        for cherg_gpv, subscribers in by_subqueue.items():
            if should_stop():
                break
            try:
                new_versions, new_messages = await self._poll_subqueue(
                    cherg_gpv, subscribers, address_counts, now
                )
                changed += new_versions
                messages += new_messages
            except SourceError as error:
                logger.warning("poll failed for subqueue %s: %s", cherg_gpv, error)
                await report_source_error(self._alerts, error, now)
                failure: Exception = error
            except Exception as error:
                logger.exception("poll crashed for subqueue %s", cherg_gpv)
                failure = error
            else:
                continue
            await self._report_if_stale(cherg_gpv, subscribers, failure, now)
        if by_subqueue:
            logger.info(
                "poll subqueues=%s changed=%s messages=%s ms=%s",
                len(by_subqueue),
                changed,
                messages,
                round((time.monotonic() - started) * 1000),
            )

    async def _report_if_stale(
        self, cherg_gpv: str, subscribers: list[Subscription], error: Exception, now: datetime
    ) -> None:
        """Never raises, so one subqueue's alert cannot cut the rest of the pass short."""
        if self._alerts is None or self._stale_after is None:
            return
        try:
            # A poll row outlives its last subscriber, so a re-subscribed subqueue counts afresh.
            since = min(subscription.created_at for subscription in subscribers)
            polled_at = await self._repository.polled_at(cherg_gpv)
            if polled_at is not None:
                since = max(since, polled_at)
        except Exception:
            logger.exception("stale check failed for subqueue %s", cherg_gpv)
            return
        if now - since > self._stale_after:
            details = f"{cherg_gpv} not polled since {since:%Y-%m-%d %H:%M} UTC: {error}"
            await self._alerts.report(AlertKind.SCHEDULE_STALE, details, now)

    async def _poll_subqueue(
        self,
        cherg_gpv: str,
        subscribers: list[Subscription],
        address_counts: Mapping[int, int],
        now: datetime,
    ) -> tuple[int, int]:
        """Returns how many versions were new and how many messages were queued."""
        schedules = await self._source.fetch_schedules(subscribers[0].address, cherg_gpv)
        previous_poll = await self._repository.polled_at(cherg_gpv)
        # A change is news only to subscribers who already had the previous poll's data, even
        # an empty one; for everyone else (and on the very first poll) this is their first load.
        recipients = [
            subscription
            for subscription in subscribers
            if subscription.notify_on_update
            and cherg_gpv in subscription.tracked_subqueues
            and previous_poll is not None
            and subscription.created_at <= previous_poll
        ]
        stored = [
            await self._store(schedule, recipients, address_counts, now) for schedule in schedules
        ]
        # Recorded after the stores, so a poll that crashes while saving still looks stale.
        await self._repository.mark_polled(cherg_gpv, now)
        return sum(is_new for is_new, _ in stored), sum(count for _, count in stored)

    async def _store(
        self,
        schedule: DaySchedule,
        recipients: list[Subscription],
        address_counts: Mapping[int, int],
        now: datetime,
    ) -> tuple[bool, int]:
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
                stale = await self._stale_reminders(change, recipients, now)
                messages = _messages(change, recipients, f"{base}:{digest}", stale, address_counts)
        version = ScheduleVersion(
            cherg_gpv=schedule.cherg_gpv,
            day=schedule.day,
            created_at=schedule.created_at,
            data_hash=digest,
            slots=schedule.slots,
            fetched_at=now,
        )
        await self._repository.save_version(version, messages)
        return previous is None or previous.data_hash != digest, len(messages)

    async def _stale_reminders(
        self, change: ScheduleChange, recipients: list[Subscription], now: datetime
    ) -> dict[int, list[str]]:
        """Per subscription, the reminded outage starts that the new schedule moved or dropped."""
        starts = {
            exact: [start.isoformat() for start in change.moved_starts(now, exact=exact)]
            for exact in (False, True)
        }
        keys = {
            (subscription.id, start): reminder_key(
                subscription, change.cherg_gpv, start, MessageKind.REMINDER_OFF
            )
            for subscription in recipients
            for start in starts[subscription.remind_exact]
        }
        if not keys:
            return {subscription.id: [] for subscription in recipients}
        queued = await self._repository.queued_keys(list(keys.values()))
        return {
            subscription.id: [
                start
                for start in starts[subscription.remind_exact]
                if keys[subscription.id, start] in queued
            ]
            for subscription in recipients
        }


def _messages(
    change: ScheduleChange,
    recipients: list[Subscription],
    transition: str,
    stale_reminders: dict[int, list[str]],
    address_counts: Mapping[int, int],
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
                "address_count": address_counts[subscription.user_id],
                "stale_reminders": stale_reminders[subscription.id],
            },
            dedupe_key=f"update:{subscription.id}:{change.cherg_gpv}:{change.day}:{transition}",
        )
        for subscription in recipients
    ]


class SchedulesByProvider:
    """A `ScheduleSource` that sends each subqueue to its oblenergo's source."""

    def __init__(self, sources: Mapping[str, ScheduleSource]) -> None:
        self._sources = sources

    async def fetch_schedules(self, address: Address, cherg_gpv: str) -> list[DaySchedule]:
        return await self._sources[provider_of(cherg_gpv)].fetch_schedules(address, cherg_gpv)

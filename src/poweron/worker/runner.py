import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime

from poweron.core.ports import Heartbeat
from poweron.core.services.backups import Backups
from poweron.core.services.groups import SubqueueChecker
from poweron.core.services.notifications import Notifications
from poweron.core.services.planned_works import PlannedWorks
from poweron.core.services.polling import Polling
from poweron.core.services.reminders import Reminders

logger = logging.getLogger(__name__)

DISPATCH_INTERVAL = 5.0
NEW_SUBQUEUE_INTERVAL = 10.0
REMINDER_INTERVAL = 60.0
CHECK_SUBQUEUES_INTERVAL = 3600.0
PLANNED_WORKS_INTERVAL = 3600.0
BACKUP_INTERVAL = 600.0
POLL_JITTER = 20.0
MIN_DELAY = 1.0


async def run_worker(
    polling: Polling,
    notifications: Notifications,
    reminders: Reminders,
    subqueue_checker: SubqueueChecker,
    planned_works: PlannedWorks,
    poll_interval: float,
    stop: asyncio.Event,
    heartbeat: Heartbeat | None = None,
    backups: Backups | None = None,
) -> None:
    """Runs the jobs until `stop` is set.

    Dispatch finishes its batch; the fetching jobs stop between items.
    """
    async with asyncio.TaskGroup() as group:
        group.create_task(
            repeat(
                lambda: poll_then_beat(polling, heartbeat, stop),
                stop,
                poll_interval,
                POLL_JITTER,
            )
        )
        if backups is not None:
            group.create_task(repeat(lambda: backups.run(datetime.now(UTC)), stop, BACKUP_INTERVAL))
        group.create_task(
            repeat(
                lambda: polling.poll_new(datetime.now(UTC), stop.is_set),
                stop,
                NEW_SUBQUEUE_INTERVAL,
            )
        )
        group.create_task(
            repeat(lambda: notifications.dispatch(datetime.now(UTC)), stop, DISPATCH_INTERVAL)
        )
        group.create_task(
            repeat(lambda: reminders.tick(datetime.now(UTC)), stop, REMINDER_INTERVAL)
        )
        group.create_task(
            repeat(
                lambda: subqueue_checker.check(datetime.now(UTC), stop.is_set),
                stop,
                CHECK_SUBQUEUES_INTERVAL,
            )
        )
        group.create_task(
            repeat(
                lambda: planned_works.check(datetime.now(UTC), stop.is_set),
                stop,
                PLANNED_WORKS_INTERVAL,
            )
        )


async def poll_then_beat(
    polling: Polling, heartbeat: Heartbeat | None, stop: asyncio.Event
) -> None:
    """The heartbeat follows a finished poll: it says the worker runs, not that every fetch worked."""
    await polling.poll(datetime.now(UTC), stop.is_set)
    if heartbeat is not None:
        await heartbeat.beat()


async def repeat(
    job: Callable[[], Awaitable[None]],
    stop: asyncio.Event,
    interval: float,
    jitter: float = 0.0,
) -> None:
    while not stop.is_set():
        try:
            await job()
        except Exception:
            logger.exception("worker job failed")
        delay = max(MIN_DELAY, interval + random.uniform(-jitter, jitter))
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), delay)

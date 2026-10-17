import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from poweron.core.services.groups import GroupResolver
from poweron.core.services.notifications import Notifications
from poweron.core.services.polling import Polling
from poweron.core.services.reminders import Reminders

logger = logging.getLogger(__name__)

DISPATCH_INTERVAL = 5.0
NEW_SUBQUEUE_INTERVAL = 10.0
REMINDER_INTERVAL = 60.0
RESOLVE_GROUPS_INTERVAL = 3600.0
POLL_JITTER = 20.0
MIN_DELAY = 1.0


async def run_worker(
    polling: Polling,
    notifications: Notifications,
    reminders: Reminders,
    group_resolver: GroupResolver,
    poll_interval: float,
) -> None:
    async with asyncio.TaskGroup() as group:
        group.create_task(
            repeat(lambda: polling.poll(datetime.now(UTC)), poll_interval, POLL_JITTER)
        )
        group.create_task(
            repeat(lambda: polling.poll_new(datetime.now(UTC)), NEW_SUBQUEUE_INTERVAL)
        )
        group.create_task(
            repeat(lambda: notifications.dispatch(datetime.now(UTC)), DISPATCH_INTERVAL)
        )
        group.create_task(repeat(lambda: reminders.tick(datetime.now(UTC)), REMINDER_INTERVAL))
        group.create_task(
            repeat(lambda: group_resolver.resolve(datetime.now(UTC)), RESOLVE_GROUPS_INTERVAL)
        )


async def repeat(
    job: Callable[[], Awaitable[None]],
    interval: float,
    jitter: float = 0.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    while True:
        try:
            await job()
        except Exception:
            logger.exception("worker job failed")
        await sleep(max(MIN_DELAY, interval + random.uniform(-jitter, jitter)))

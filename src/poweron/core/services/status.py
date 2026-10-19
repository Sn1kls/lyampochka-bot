from datetime import timedelta

from poweron.core.domain.models import StatusReport, SubqueueStatus
from poweron.core.ports import Repository
from poweron.core.services.notifications import MAX_ATTEMPTS

STALE_POLL_INTERVALS = 3


class Status:
    def __init__(self, repository: Repository, version: str, poll_interval: timedelta) -> None:
        self._repository = repository
        self._version = version
        self._stale_after = STALE_POLL_INTERVALS * poll_interval

    async def report(self) -> StatusReport:
        subscriptions = await self._repository.all_subscriptions()
        subqueues = sorted({cherg_gpv for item in subscriptions for cherg_gpv in item.subqueues})
        polled = [
            SubqueueStatus(
                cherg_gpv,
                await self._repository.polled_at(cherg_gpv),
                await self._repository.latest_schedule_day(cherg_gpv),
            )
            for cherg_gpv in subqueues
        ]
        return StatusReport(
            version=self._version,
            users=await self._repository.count_users(),
            subscriptions=len(subscriptions),
            pending_messages=await self._repository.count_pending_messages(MAX_ATTEMPTS),
            subqueues=tuple(polled),
            stale_after=self._stale_after,
        )

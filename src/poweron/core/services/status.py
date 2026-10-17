from poweron.core.domain.models import StatusReport, SubqueueStatus
from poweron.core.ports import Repository
from poweron.core.services.notifications import MAX_ATTEMPTS


class Status:
    def __init__(self, repository: Repository, version: str) -> None:
        self._repository = repository
        self._version = version

    async def report(self) -> StatusReport:
        subscriptions = await self._repository.all_subscriptions()
        subqueues = sorted({cherg_gpv for item in subscriptions for cherg_gpv in item.subqueues})
        polled = [
            SubqueueStatus(cherg_gpv, await self._repository.last_polled_at(cherg_gpv))
            for cherg_gpv in subqueues
        ]
        return StatusReport(
            version=self._version,
            users=await self._repository.count_users(),
            subscriptions=len(subscriptions),
            pending_messages=await self._repository.count_pending_messages(MAX_ATTEMPTS),
            subqueues=tuple(polled),
        )

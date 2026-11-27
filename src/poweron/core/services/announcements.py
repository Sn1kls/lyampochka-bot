from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, OutboxMessage
from poweron.core.ports import Repository

# Someone who joined a moment ago may still be adding the address.
NEW_USER_GRACE = timedelta(days=1)


class Announcements:
    """One-off messages to every user, delivered through the outbox like any push."""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def menu_updated(self, version: int) -> int:
        """Queues the new Telegram menu for every reachable user, at most once per `version`.

        Returns how many messages were newly queued, so a rerun without a version bump shows 0.
        """
        return await self._repository.enqueue_messages(
            [
                OutboxMessage(user_id, MessageKind.MENU_UPDATED, {}, f"menu:{version}:{user_id}")
                for user_id in await self._repository.user_ids_on("telegram")
            ]
        )

    async def nudge_without_address(self, now: datetime) -> int:
        """Reminds each user with no address now to add one, once ever.

        A user who removed their only address gets it too: removal leaves no trace.
        """
        user_ids = await self._repository.user_ids_without_address("telegram", now - NEW_USER_GRACE)
        return await self._repository.enqueue_messages(
            [
                OutboxMessage(user_id, MessageKind.NO_ADDRESS, {}, f"no-address:{user_id}")
                for user_id in user_ids
            ]
        )

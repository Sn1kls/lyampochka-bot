from datetime import datetime, timedelta

from poweron.core.domain.models import KYIV, MessageKind, OutboxMessage
from poweron.core.ports import Repository

# Someone who joined a moment ago may still be adding the address.
NEW_USER_GRACE = timedelta(hours=1)
# An older user with no address most likely removed it, perhaps to add another one right now.
NEW_USER_WINDOW = timedelta(days=7)
# Kyiv hours when a nudge waits for the morning instead of waking someone up.
QUIET_FROM, QUIET_UNTIL = 22, 8


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
        """Reminds each new user with no address to add one, once ever; never at night."""
        hour = now.astimezone(KYIV).hour
        if hour >= QUIET_FROM or hour < QUIET_UNTIL:
            return 0
        user_ids = await self._repository.user_ids_without_address(
            "telegram", now - NEW_USER_WINDOW, now - NEW_USER_GRACE
        )
        return await self._repository.enqueue_messages(
            [
                OutboxMessage(user_id, MessageKind.NO_ADDRESS, {}, f"no-address:{user_id}")
                for user_id in user_ids
            ]
        )

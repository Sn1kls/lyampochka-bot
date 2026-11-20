from collections import defaultdict, deque
from datetime import datetime, timedelta

from poweron.core.domain.models import MessageKind, OutboxMessage
from poweron.core.ports import Repository


class Feedback:
    """Users write to the admin and the admin replies; the messages themselves stay in the channel.

    The rate limit lives in memory, so a restart resets it: enough against a flood.
    """

    def __init__(
        self, repository: Repository, limit: int = 5, window: timedelta = timedelta(hours=1)
    ) -> None:
        self._repository = repository
        self._limit = limit
        self._window = window
        self._accepted: defaultdict[int, deque[datetime]] = defaultdict(deque)

    def accept(self, user_id: int, now: datetime) -> timedelta | None:
        """Counts one feedback; over the limit, returns how long to wait instead."""
        accepted = self._accepted[user_id]
        while accepted and now - accepted[0] >= self._window:
            accepted.popleft()
        if len(accepted) >= self._limit:
            return accepted[0] + self._window - now
        accepted.append(now)
        return None

    async def reply(self, user_id: int, text: str, reply_key: str) -> bool:
        """Queues the admin's reply once per `reply_key`; False when the user is gone."""
        if not await self._repository.delivery_targets(user_id):
            return False
        message = OutboxMessage(
            user_id, MessageKind.FEEDBACK_REPLY, {"text": text}, f"feedback:{reply_key}"
        )
        await self._repository.enqueue_messages([message])
        return True

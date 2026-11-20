from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import datetime, timedelta

from poweron.core.domain.models import FeedbackThread, MessageKind, OutboxMessage
from poweron.core.ports import Repository


class Feedback:
    """Users write to the admin and the admin replies; the messages themselves stay in the channel.

    A channel passes opaque `refs` of its admin-side copies, so a reply finds its author by
    message, never by text a user could forge. The rate limit lives in memory, so a restart
    resets it: enough against a flood.
    """

    def __init__(
        self, repository: Repository, limit: int = 5, window: timedelta = timedelta(hours=1)
    ) -> None:
        self._repository = repository
        self._limit = limit
        self._window = window
        self._received: defaultdict[int, deque[datetime]] = defaultdict(deque)

    def wait(self, user_id: int, now: datetime) -> timedelta | None:
        """How long the user must wait before the next feedback; None when they may send now."""
        received = self._received[user_id]
        while received and now - received[0] >= self._window:
            received.popleft()
        return received[0] + self._window - now if len(received) >= self._limit else None

    async def received(self, user_id: int, refs: Sequence[str], now: datetime) -> None:
        """Counts one feedback and remembers its admin-side copies."""
        self._received[user_id].append(now)
        await self._repository.add_feedback_messages(user_id, refs, now)

    async def thread(self, ref: str) -> FeedbackThread | None:
        """The author behind an admin-side message; None when it is not a feedback copy."""
        return await self._repository.feedback_thread(ref)

    async def reply(self, user_id: int, text: str, reply_key: str) -> bool:
        """Queues the admin's reply once per `reply_key`; False when the user cannot be reached."""
        if not await self._repository.delivery_targets(user_id):
            return False
        message = OutboxMessage(
            user_id, MessageKind.FEEDBACK_REPLY, {"text": text}, f"feedback:{reply_key}"
        )
        await self._repository.enqueue_messages([message])
        return True

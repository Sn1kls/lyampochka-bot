from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import datetime, timedelta

from poweron.core.domain.models import FeedbackThread, MessageKind, OutboxMessage
from poweron.core.ports import Repository


class Feedback:
    """Users write to the admin and the admin replies; the messages themselves stay in the channel.

    A channel passes opaque `refs` of its admin-side copies, so a reply finds its author by
    message, never by text a user could forge. The rate limit counts by the channel's opaque
    `sender` key, not by `user_id`: forgetting oneself gives a new `user_id`, never a new
    account. It lives in memory only, so a restart resets it: enough against a flood.
    """

    def __init__(
        self, repository: Repository, limit: int = 5, window: timedelta = timedelta(hours=1)
    ) -> None:
        self._repository = repository
        self._limit = limit
        self._window = window
        self._received: defaultdict[str, deque[datetime]] = defaultdict(deque)

    def retry_after(self, sender: str, now: datetime) -> timedelta | None:
        """How long the sender must wait before the next feedback; None when they may send now."""
        received = self._received[sender]
        while received and now - received[0] >= self._window:
            received.popleft()
        return received[0] + self._window - now if len(received) >= self._limit else None

    async def record(
        self,
        user_id: int,
        sender: str,
        source_message_id: int,
        refs: Sequence[str],
        now: datetime,
    ) -> None:
        """Counts one feedback and remembers its admin-side copies."""
        self._received[sender].append(now)
        await self._repository.add_feedback_messages(user_id, source_message_id, refs, now)

    async def thread(self, ref: str) -> FeedbackThread | None:
        """The author behind an admin-side message; None when it is not a feedback copy."""
        return await self._repository.feedback_thread(ref)

    async def reply(
        self, thread: FeedbackThread, text: str, reply_key: str, answer_message_id: int
    ) -> bool:
        """Queues the admin's reply once per `reply_key`; False when the user cannot be reached.

        `answer_message_id` is the admin's own message, so the user's Reply to the delivered
        answer can point back at it (see Notifications).
        """
        if thread.user_id is None or not await self._repository.delivery_targets(thread.user_id):
            return False
        payload = {
            "text": text,
            "reply_to": thread.source_message_id,
            "answer": answer_message_id,
        }
        message = OutboxMessage(
            thread.user_id, MessageKind.FEEDBACK_REPLY, payload, f"feedback:{reply_key}"
        )
        await self._repository.enqueue_messages([message])
        return True

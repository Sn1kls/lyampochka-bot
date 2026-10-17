import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from poweron.core.domain.models import OutboxMessage
from poweron.core.ports import DeliveryTargetGone, Notifier, Repository

logger = logging.getLogger(__name__)

BATCH_SIZE = 50
MAX_ATTEMPTS = 5
FIRST_RETRY_DELAY = timedelta(seconds=30)


class Notifications:
    def __init__(self, repository: Repository, notifiers: Mapping[str, Notifier]) -> None:
        self._repository = repository
        self._notifiers = notifiers

    async def dispatch(self, now: datetime) -> None:
        """Send due outbox messages; a failure is retried later with exponential backoff."""
        for queued in await self._repository.due_messages(now, BATCH_SIZE, MAX_ATTEMPTS):
            try:
                await self._deliver(queued.message)
            except Exception as error:  # any channel failure must not stop the batch
                if queued.attempts + 1 >= MAX_ATTEMPTS:
                    logger.error("giving up on message %s: %r", queued.id, error)
                else:
                    logger.warning("delivery of message %s failed: %r", queued.id, error)
                retry_at = now + FIRST_RETRY_DELAY * 2**queued.attempts
                await self._repository.mark_failed(queued.id, repr(error), retry_at)
            else:
                await self._repository.mark_sent(queued.id, now)

    async def _deliver(self, message: OutboxMessage) -> None:
        # At-least-once: a failure on one target retries the message for all of them.
        # Fine with a single channel; fan out per target once a second channel exists.
        for target in await self._repository.delivery_targets(message.user_id):
            notifier = self._notifiers.get(target.channel)
            if notifier is None:
                logger.warning("no notifier for channel %s", target.channel)
                continue
            try:
                await notifier.send(target.address, message.kind, message.payload)
            except DeliveryTargetGone:
                await self._repository.deactivate_target(target.id)

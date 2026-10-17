from datetime import datetime

from poweron.core.ports import Repository


class Reminders:
    """Queues "power goes off / comes back in N minutes" messages.

    Payload of `reminder_off` / `reminder_on`: {"subscription_id": int, "label": str,
    "cherg_gpv": str, "queue_count": int (tracked queues), "minutes": int,
    "earliest": ISO datetime, "latest": ISO datetime | None} — the event window of NextEvent.
    """

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    async def tick(self, now: datetime) -> None:
        raise NotImplementedError

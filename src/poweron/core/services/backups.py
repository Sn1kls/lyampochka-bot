import logging
from datetime import date, datetime

from poweron.core.domain.models import KYIV, AlertKind
from poweron.core.ports import BackupSink, Repository
from poweron.core.services.alerts import Alerts

logger = logging.getLogger(__name__)

BACKUP_HOUR = 4


class Backups:
    """A daily database backup during BACKUP_HOUR (Kyiv); a day the worker was down is skipped."""

    def __init__(
        self, repository: Repository, sink: BackupSink, alerts: Alerts | None = None
    ) -> None:
        self._repository = repository
        self._sink = sink
        self._alerts = alerts
        self._last_day: date | None = None

    async def run(self, now: datetime) -> None:
        local = now.astimezone(KYIV)
        if local.hour != BACKUP_HOUR or self._last_day == local.date():
            return
        try:
            content = await self._repository.snapshot()
            await self._sink.store(f"poweron-{local:%Y-%m-%d}.sqlite3", content)
        except Exception as error:
            # Retried on the next run within the hour; the owner hears about it at most hourly.
            logger.exception("backup failed")
            if self._alerts is not None:
                await self._alerts.report(AlertKind.BACKUP_FAILED, type(error).__name__, now)
            return
        self._last_day = local.date()
        logger.info("backup stored bytes=%d", len(content))

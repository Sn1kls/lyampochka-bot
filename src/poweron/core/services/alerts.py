import logging
from datetime import datetime, timedelta

from poweron.core.domain.models import AlertKind
from poweron.core.ports import AdminAlerter, ApiSchemaError, SourceError

logger = logging.getLogger(__name__)


class Alerts:
    """Admin alerts, at most one per kind per `interval` (SPEC §9)."""

    def __init__(self, alerter: AdminAlerter, interval: timedelta = timedelta(hours=1)) -> None:
        self._alerter = alerter
        self._interval = interval
        self._last_sent: dict[AlertKind, datetime] = {}

    async def report(self, kind: AlertKind, details: str, now: datetime) -> None:
        last_sent = self._last_sent.get(kind)
        if last_sent is not None and now - last_sent < self._interval:
            return
        self._last_sent[kind] = now
        try:
            await self._alerter.alert(kind, details)
        except Exception as error:
            logger.warning("admin alert %s was not delivered: %r", kind, error)


async def report_source_error(alerts: Alerts | None, error: SourceError, now: datetime) -> None:
    if alerts is not None:
        kind = AlertKind.API_SCHEMA if isinstance(error, ApiSchemaError) else AlertKind.API_DOWN
        await alerts.report(kind, str(error), now)

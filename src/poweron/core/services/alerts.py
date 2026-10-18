import logging
from datetime import datetime, timedelta

from poweron.core.domain.models import AlertKind
from poweron.core.ports import AdminAlerter, ApiSchemaError, SourceError, SourcePaused

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
        try:
            await self._alerter.alert(kind, details)
        except Exception as error:
            logger.warning("admin alert %s was not delivered: %r", kind, error)
        else:
            self._last_sent[kind] = now


async def report_source_error(alerts: Alerts | None, error: SourceError, now: datetime) -> None:
    """Only a schema break or a sustained outage is worth an alert; one failed request is not."""
    if alerts is None:
        return
    if isinstance(error, ApiSchemaError):
        await alerts.report(AlertKind.API_SCHEMA, str(error), now)
    elif isinstance(error, SourcePaused):
        await alerts.report(AlertKind.API_DOWN, str(error), now)

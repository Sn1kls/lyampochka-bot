from datetime import datetime, timedelta

from poweron.core.domain.models import AlertKind
from poweron.core.ports import AdminAlerter


class Alerts:
    """Admin alerts, at most one per kind per `interval` (SPEC §9)."""

    def __init__(self, alerter: AdminAlerter, interval: timedelta = timedelta(hours=1)) -> None:
        self._alerter = alerter
        self._interval = interval

    async def report(self, kind: AlertKind, details: str, now: datetime) -> None:
        raise NotImplementedError

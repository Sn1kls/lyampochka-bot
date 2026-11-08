from datetime import datetime, timedelta

from poweron.core.domain.models import AlertKind
from poweron.core.domain.providers import VOE_CATALOG_IMPORTED_KEY
from poweron.core.ports import Repository
from poweron.core.services.alerts import Alerts

# The export runs weekly; a few missed runs are fine, a forgotten Mac is not.
STALE_AFTER = timedelta(days=10)


class VoeCatalogAge:
    """Tells the admin when the weekly Volyn queue import stopped arriving."""

    def __init__(self, repository: Repository, alerts: Alerts) -> None:
        self._repository = repository
        self._alerts = alerts

    async def check(self, now: datetime) -> None:
        imported = await self._repository.cached_catalog(VOE_CATALOG_IMPORTED_KEY)
        age = None if imported is None else now - imported[1]
        if age is None or age > STALE_AFTER:
            details = "no import yet" if age is None else f"last import {age.days} days ago"
            await self._alerts.report(AlertKind.VOE_CATALOG_STALE, details, now)

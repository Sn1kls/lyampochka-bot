from dataclasses import dataclass, field

from poweron.core.domain.models import AlertKind


@dataclass
class FakeAlerter:
    alerts: list[tuple[AlertKind, str]] = field(default_factory=list)
    error: Exception | None = None

    async def alert(self, kind: AlertKind, details: str) -> None:
        if self.error:
            raise self.error
        self.alerts.append((kind, details))

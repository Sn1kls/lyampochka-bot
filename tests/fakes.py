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


class FakeClock:
    """A monotonic clock that `sleep` moves forward at once."""

    def __init__(self) -> None:
        self.monotonic_now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.monotonic_now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_now += seconds


def blocks(codes: str) -> list[tuple[str, str]]:
    """OFF ("1") stretches of 48 half-hour slot codes as ("HH:MM", "HH:MM") pairs."""

    def clock_time(index: int) -> str:
        return f"{index // 2:02d}:{index % 2 * 30:02d}"

    found = []
    start = None
    for index, code in enumerate(codes + "0"):
        if code == "1" and start is None:
            start = index
        if code == "0" and start is not None:
            found.append((clock_time(start), clock_time(index)))
            start = None
    return found

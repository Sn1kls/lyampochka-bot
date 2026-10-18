import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import KYIV, AlertKind
from poweron.core.services.alerts import Alerts
from poweron.core.services.backups import Backups
from poweron.core.services.subscriptions import Subscriptions
from tests.fakes import FakeAlerter

FOUR_AM = datetime(2026, 10, 19, 4, 5, tzinfo=KYIV)


@dataclass
class FakeSink:
    stored: list[tuple[str, bytes]] = field(default_factory=list)
    error: Exception | None = None

    async def store(self, name: str, content: bytes) -> None:
        if self.error is not None:
            raise self.error
        self.stored.append((name, content))


async def test_one_backup_a_day_at_four_in_the_morning(repository: SqlRepository) -> None:
    sink = FakeSink()
    backups = Backups(repository, sink)

    await backups.run(FOUR_AM - timedelta(hours=1))
    await backups.run(FOUR_AM)
    await backups.run(FOUR_AM + timedelta(minutes=10))
    await backups.run(FOUR_AM + timedelta(days=1))

    assert [name for name, _ in sink.stored] == [
        "poweron-2026-10-19.sqlite3",
        "poweron-2026-10-20.sqlite3",
    ]


async def test_the_backup_is_a_full_copy_of_the_database(repository: SqlRepository) -> None:
    await Subscriptions(repository).register("telegram", "101", "telegram", "101")
    sink = FakeSink()

    await Backups(repository, sink).run(FOUR_AM)

    copy = sqlite3.connect(":memory:")
    copy.deserialize(sink.stored[0][1])
    assert copy.execute("select count(*) from users").fetchone() == (1,)


async def test_a_failed_backup_alerts_the_admin_and_is_retried(repository: SqlRepository) -> None:
    sink = FakeSink(error=RuntimeError("telegram is down"))
    alerter = FakeAlerter()
    backups = Backups(repository, sink, Alerts(alerter))

    await backups.run(FOUR_AM)
    sink.error = None
    await backups.run(FOUR_AM + timedelta(minutes=10))

    assert alerter.alerts == [(AlertKind.BACKUP_FAILED, "RuntimeError")]
    assert len(sink.stored) == 1

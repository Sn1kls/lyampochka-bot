from dataclasses import dataclass
from datetime import timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import (
    AlertKind,
    Building,
    City,
    MessageKind,
    OutboxMessage,
    Street,
)
from poweron.core.ports import ApiSchemaError, SourcePaused, SourceUnavailable
from poweron.core.services.alerts import Alerts
from poweron.core.services.groups import RECHECK_AFTER, SubqueueChecker
from poweron.core.services.notifications import MAX_ATTEMPTS
from poweron.core.services.planned_works import PlannedWorks
from poweron.core.services.polling import Polling
from poweron.core.services.status import Status
from poweron.core.services.subscriptions import Subscriptions
from tests.fakes import FakeAlerter
from tests.services.conftest import NOW

TERNOPIL = City(id=1032, name="Тернопіль", otg_name=None)
SADOVA = Street(id=9985, name="вул. Садова")
POLL_INTERVAL = timedelta(minutes=5)


@dataclass
class BrokenSource:
    error: Exception

    async def fetch_schedules(self, *_: object) -> list[object]:
        raise self.error

    async def building_subqueues(self, *_: object) -> list[str]:
        raise self.error

    async def planned_works(self, *_: object) -> list[object]:
        raise self.error


@pytest.fixture
def alerter() -> FakeAlerter:
    return FakeAlerter()


@pytest.fixture
def alerts(alerter: FakeAlerter) -> Alerts:
    return Alerts(alerter)


async def subscribe(repository: SqlRepository, external_id: str = "101") -> int:
    subscriptions = Subscriptions(repository)
    user_id = await subscriptions.register("telegram", external_id, "telegram", external_id)
    building = Building(1, "1", "4.1")
    await subscriptions.add(user_id, "Дім", TERNOPIL, SADOVA, building, ["4.1"], ["4.1"], NOW)
    return user_id


async def test_one_alert_per_kind_per_interval(alerter: FakeAlerter, alerts: Alerts) -> None:
    await alerts.report(AlertKind.API_DOWN, "first", NOW)
    await alerts.report(AlertKind.API_DOWN, "second", NOW + timedelta(minutes=59))
    await alerts.report(AlertKind.API_SCHEMA, "other kind", NOW + timedelta(minutes=59))
    await alerts.report(AlertKind.API_DOWN, "third", NOW + timedelta(hours=1))

    assert alerter.alerts == [
        (AlertKind.API_DOWN, "first"),
        (AlertKind.API_SCHEMA, "other kind"),
        (AlertKind.API_DOWN, "third"),
    ]


async def test_a_failing_alerter_never_raises(alerter: FakeAlerter, alerts: Alerts) -> None:
    alerter.error = RuntimeError("telegram is down")

    await alerts.report(AlertKind.API_DOWN, "details", NOW)


async def test_schema_error_in_polling_alerts_once_within_the_hour(
    repository: SqlRepository, alerter: FakeAlerter, alerts: Alerts
) -> None:
    await subscribe(repository)
    polling = Polling(repository, BrokenSource(ApiSchemaError("bad shape")), alerts)

    await polling.poll(NOW)
    await polling.poll(NOW + timedelta(minutes=10))

    assert alerter.alerts == [(AlertKind.API_SCHEMA, "bad shape")]


async def test_a_paused_source_alerts_in_every_job(
    repository: SqlRepository, alerter: FakeAlerter, alerts: Alerts
) -> None:
    await subscribe(repository)
    source = BrokenSource(SourcePaused("down"))

    await Polling(repository, source, alerts).poll(NOW)
    await SubqueueChecker(repository, source, alerts).check(NOW + RECHECK_AFTER)
    await PlannedWorks(repository, source, alerts).check(NOW)

    assert alerter.alerts == [(AlertKind.API_DOWN, "down")]


async def test_a_one_off_failure_does_not_alert(
    repository: SqlRepository, alerter: FakeAlerter, alerts: Alerts
) -> None:
    await subscribe(repository)

    await Polling(repository, BrokenSource(SourceUnavailable("blip")), alerts).poll(NOW)

    assert alerter.alerts == []


async def test_a_failed_send_is_retried_on_the_next_report(
    alerter: FakeAlerter, alerts: Alerts
) -> None:
    alerter.error = RuntimeError("telegram is down")
    await alerts.report(AlertKind.API_DOWN, "first", NOW)

    alerter.error = None
    await alerts.report(AlertKind.API_DOWN, "second", NOW + timedelta(minutes=1))

    assert alerter.alerts == [(AlertKind.API_DOWN, "second")]


async def test_every_new_user_is_announced_once(
    repository: SqlRepository, alerter: FakeAlerter, alerts: Alerts
) -> None:
    subscriptions = Subscriptions(repository, alerts)

    await subscriptions.register("telegram", "101", "telegram", "101", "Оля @olya")
    await subscriptions.register("telegram", "101", "telegram", "101", "Оля @olya")
    await subscriptions.register("telegram", "102", "telegram", "102", "Петро")

    assert alerter.alerts == [
        (AlertKind.NEW_USER, "Оля @olya"),
        (AlertKind.NEW_USER, "Петро"),
    ]


async def test_registration_survives_a_failing_alerter(
    repository: SqlRepository, alerter: FakeAlerter, alerts: Alerts
) -> None:
    alerter.error = RuntimeError("telegram is down")

    user_id = await Subscriptions(repository, alerts).register(
        "telegram", "101", "telegram", "101", "Оля"
    )

    assert await repository.find_user("telegram", "101") == user_id


async def test_jobs_work_without_alerts(repository: SqlRepository) -> None:
    await subscribe(repository)
    source = BrokenSource(SourceUnavailable("down"))

    await Polling(repository, source).poll(NOW)
    await SubqueueChecker(repository, source).check(NOW + RECHECK_AFTER)
    await PlannedWorks(repository, source).check(NOW)


async def test_status_counts_what_is_pending(repository: SqlRepository) -> None:
    empty = await Status(repository, "1.2.3", POLL_INTERVAL).report()
    assert (empty.users, empty.subscriptions, empty.pending_messages, empty.subqueues) == (
        0,
        0,
        0,
        (),
    )

    user_id = await subscribe(repository, "101")
    await subscribe(repository, "102")

    def message(key: str) -> OutboxMessage:
        return OutboxMessage(user_id, MessageKind.SCHEDULE_UPDATED, {}, key)

    await repository.enqueue_messages([message("sent"), message("given-up"), message("pending")])
    queued = {item.message.dedupe_key: item for item in await repository.due_messages(NOW, 10, 5)}
    await repository.mark_sent(queued["sent"].id, NOW)
    for _ in range(MAX_ATTEMPTS):
        await repository.mark_failed(queued["given-up"].id, "boom", NOW)

    report = await Status(repository, "1.2.3", POLL_INTERVAL).report()

    assert report.version == "1.2.3"
    assert report.stale_after == timedelta(minutes=15)
    assert (report.users, report.subscriptions, report.pending_messages) == (2, 2, 1)
    [subqueue] = report.subqueues
    assert (subqueue.cherg_gpv, subqueue.last_polled_at) == ("4.1", None)

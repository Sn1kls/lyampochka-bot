from datetime import UTC, datetime, timedelta

import pytest

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import KYIV
from poweron.core.services import announcements as announcements_module
from poweron.core.services.announcements import Announcements
from poweron.core.services.notifications import Notifications
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, FakeNotifier, subscribe


def tomorrow_at(hour: int, minute: int = 0) -> datetime:
    """Kyiv time of day, a day after users joined (they join on the real clock)."""
    day = datetime.now(KYIV) + timedelta(days=1)
    return day.replace(hour=hour, minute=minute, second=0, microsecond=0)


async def register(repository: SqlRepository, *chat_ids: str) -> list[int]:
    subscriptions = Subscriptions(repository)
    return [
        await subscriptions.register("telegram", chat_id, "telegram", chat_id, now=NOW)
        for chat_id in chat_ids
    ]


async def test_a_menu_update_reaches_every_telegram_user_once(repository: SqlRepository) -> None:
    await register(repository, "101", "102")
    announcements = Announcements(repository)
    notifier = FakeNotifier()

    assert await announcements.menu_updated(2) == 2
    assert await announcements.menu_updated(2) == 0
    await Notifications(repository, {"telegram": notifier}).dispatch(NOW)

    assert notifier.sent == [("101", "menu_updated", {}), ("102", "menu_updated", {})]


async def test_a_new_menu_version_is_announced_again(repository: SqlRepository) -> None:
    await register(repository, "101")
    announcements = Announcements(repository)

    assert await announcements.menu_updated(2) == 1
    assert await announcements.menu_updated(3) == 1


async def test_users_who_blocked_the_bot_are_skipped(repository: SqlRepository) -> None:
    [blocked, _] = await register(repository, "101", "102")
    [target] = await repository.delivery_targets(blocked)
    await repository.deactivate_target(target.id)

    assert await Announcements(repository).menu_updated(2) == 1
    assert blocked not in await repository.user_ids_on("telegram")


async def test_users_without_an_address_are_nudged_once(repository: SqlRepository) -> None:
    await register(repository, "101")
    await subscribe(repository, "102")
    announcements = Announcements(repository)
    notifier = FakeNotifier()
    later = tomorrow_at(12)

    assert await announcements.nudge_without_address(later) == 1
    assert await announcements.nudge_without_address(later) == 0
    await Notifications(repository, {"telegram": notifier}).dispatch(later)

    assert notifier.sent == [("101", "no_address", {})]


async def test_a_user_is_nudged_an_hour_after_joining(
    repository: SqlRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(announcements_module, "QUIET_FROM", 24)  # no night, whenever it runs
    await register(repository, "101")
    announcements = Announcements(repository)
    joined = datetime.now(UTC)

    assert await announcements.nudge_without_address(joined + timedelta(minutes=50)) == 0
    assert await announcements.nudge_without_address(tomorrow_at(12)) == 1


async def test_no_nudge_at_night_it_waits_for_the_morning(repository: SqlRepository) -> None:
    await register(repository, "101")
    announcements = Announcements(repository)

    assert await announcements.nudge_without_address(tomorrow_at(22)) == 0
    assert await announcements.nudge_without_address(tomorrow_at(7, 59)) == 0
    assert await announcements.nudge_without_address(tomorrow_at(8)) == 1


async def test_a_user_who_joined_long_ago_is_not_nudged(repository: SqlRepository) -> None:
    # Most likely someone who removed their address to add another one.
    await register(repository, "101")
    week_later = tomorrow_at(12) + timedelta(days=7)

    assert await Announcements(repository).nudge_without_address(week_later) == 0

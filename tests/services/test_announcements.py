from poweron.adapters.db.repository import SqlRepository
from poweron.core.services.announcements import Announcements
from poweron.core.services.notifications import Notifications
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, FakeNotifier


async def register(repository: SqlRepository, *chat_ids: str) -> list[int]:
    subscriptions = Subscriptions(repository)
    return [
        await subscriptions.register("telegram", chat_id, "telegram", chat_id)
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

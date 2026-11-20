from datetime import timedelta

from poweron.adapters.db.repository import SqlRepository
from poweron.core.services.feedback import Feedback
from poweron.core.services.notifications import Notifications
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, FakeNotifier


async def register(repository: SqlRepository, chat_id: str) -> int:
    return await Subscriptions(repository).register("telegram", chat_id, "telegram", chat_id)


def test_the_sixth_feedback_within_an_hour_is_refused_until_the_first_one_ages_out(
    repository: SqlRepository,
) -> None:
    feedback = Feedback(repository, limit=5, window=timedelta(hours=1))
    for minute in range(5):
        assert feedback.accept(7, NOW + timedelta(minutes=minute)) is None

    assert feedback.accept(7, NOW + timedelta(minutes=10)) == timedelta(minutes=50)
    assert feedback.accept(8, NOW + timedelta(minutes=10)) is None
    assert feedback.accept(7, NOW + timedelta(hours=1)) is None


async def test_a_reply_reaches_the_user_once_per_reply_key(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)
    notifier = FakeNotifier()

    assert await feedback.reply(user_id, "Дякую, гляну", "admin:55")
    assert await feedback.reply(user_id, "Дякую, гляну", "admin:55")
    await Notifications(repository, {"telegram": notifier}).dispatch(NOW)

    assert notifier.sent == [("101", "feedback_reply", {"text": "Дякую, гляну"})]


async def test_a_reply_to_a_forgotten_user_is_not_queued(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    await Subscriptions(repository).forget(user_id)

    assert not await Feedback(repository).reply(user_id, "Дякую", "admin:56")

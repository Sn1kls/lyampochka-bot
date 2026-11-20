from datetime import timedelta

from poweron.adapters.db.repository import SqlRepository
from poweron.core.domain.models import FeedbackThread
from poweron.core.services.feedback import Feedback
from poweron.core.services.notifications import Notifications
from poweron.core.services.subscriptions import Subscriptions
from tests.services.conftest import NOW, FakeNotifier


async def register(repository: SqlRepository, chat_id: str) -> int:
    return await Subscriptions(repository).register("telegram", chat_id, "telegram", chat_id)


async def test_the_sixth_feedback_within_an_hour_waits_until_the_first_one_ages_out(
    repository: SqlRepository,
) -> None:
    user_id = await register(repository, "101")
    other = await register(repository, "102")
    feedback = Feedback(repository, limit=5, window=timedelta(hours=1))
    for minute in range(5):
        moment = NOW + timedelta(minutes=minute)
        assert feedback.wait(user_id, moment) is None
        await feedback.received(user_id, [f"telegram:1:{minute}"], moment)

    assert feedback.wait(user_id, NOW + timedelta(minutes=10)) == timedelta(minutes=50)
    assert feedback.wait(other, NOW + timedelta(minutes=10)) is None
    assert feedback.wait(user_id, NOW + timedelta(hours=1)) is None


async def test_every_admin_copy_leads_back_to_its_author(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)

    await feedback.received(user_id, ["telegram:1:50", "telegram:1:51"], NOW)

    assert await feedback.thread("telegram:1:51") == FeedbackThread(user_id)
    assert await feedback.thread("telegram:1:52") is None


async def test_a_forgotten_author_leaves_the_thread_without_a_user(
    repository: SqlRepository,
) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)
    await feedback.received(user_id, ["telegram:1:50"], NOW)

    await Subscriptions(repository).forget(user_id)

    assert await feedback.thread("telegram:1:50") == FeedbackThread(None)


async def test_a_reply_reaches_the_user_once_per_reply_key(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)
    notifier = FakeNotifier()

    assert await feedback.reply(user_id, "Дякую, гляну", "admin:55")
    assert await feedback.reply(user_id, "Дякую, гляну", "admin:55")
    await Notifications(repository, {"telegram": notifier}).dispatch(NOW)

    assert notifier.sent == [("101", "feedback_reply", {"text": "Дякую, гляну"})]


async def test_a_reply_to_a_user_without_a_chat_is_not_queued(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    [target] = await repository.delivery_targets(user_id)
    await repository.deactivate_target(target.id)

    assert not await Feedback(repository).reply(user_id, "Дякую", "admin:56")

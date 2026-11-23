from datetime import timedelta

import pytest

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
    feedback = Feedback(repository, limit=5, window=timedelta(hours=1))
    for minute in range(5):
        moment = NOW + timedelta(minutes=minute)
        assert feedback.retry_after("telegram:101", moment) is None
        await feedback.record(user_id, "telegram:101", minute, [f"telegram:1:{minute}"], moment)

    later = NOW + timedelta(minutes=10)
    assert feedback.retry_after("telegram:101", later) == timedelta(minutes=50)
    assert feedback.retry_after("telegram:102", later) is None
    assert feedback.retry_after("telegram:101", NOW + timedelta(hours=1)) is None


async def test_every_admin_copy_leads_back_to_its_author(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)

    await feedback.record(user_id, "telegram:101", 40, ["telegram:1:50", "telegram:1:51"], NOW)

    assert await feedback.thread("telegram:1:51") == FeedbackThread(user_id, 40)
    assert await feedback.thread("telegram:1:52") is None


async def test_a_forgotten_author_leaves_the_thread_without_a_user(
    repository: SqlRepository,
) -> None:
    user_id = await register(repository, "101")
    feedback = Feedback(repository)
    await feedback.record(user_id, "telegram:101", 40, ["telegram:1:50"], NOW)

    await Subscriptions(repository).forget(user_id)

    assert await feedback.thread("telegram:1:50") == FeedbackThread(None, 40)
    assert not await feedback.reply(FeedbackThread(None, 40), "Дякую", "admin:57", 57)


async def test_a_reply_answers_the_users_message_once_per_reply_key(
    repository: SqlRepository,
) -> None:
    thread = FeedbackThread(await register(repository, "101"), 40)
    feedback = Feedback(repository)
    notifier = FakeNotifier()

    assert await feedback.reply(thread, "Дякую, гляну", "admin:55", 55)
    assert await feedback.reply(thread, "Дякую, гляну", "admin:55", 55)
    await Notifications(repository, {"telegram": notifier}).dispatch(NOW)

    payload = {"text": "Дякую, гляну", "reply_to": 40, "answer": 55}
    assert notifier.sent == [("101", "feedback_reply", payload)]
    # The delivered answer leads back to the admin's message, for the user's Reply to it.
    assert await feedback.thread("fake:101:1") == FeedbackThread(thread.user_id, 55)


async def test_a_reply_to_a_user_without_a_chat_is_not_queued(repository: SqlRepository) -> None:
    user_id = await register(repository, "101")
    [target] = await repository.delivery_targets(user_id)
    await repository.deactivate_target(target.id)

    assert not await Feedback(repository).reply(
        FeedbackThread(user_id, 40), "Дякую", "admin:56", 56
    )


async def test_an_answer_is_not_sent_twice_when_remembering_it_fails(
    repository: SqlRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread = FeedbackThread(await register(repository, "101"), 40)
    await Feedback(repository).reply(thread, "Дякую", "admin:58", 58)
    notifier = FakeNotifier()
    dispatch = Notifications(repository, {"telegram": notifier}).dispatch

    async def locked(*args: object) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(repository, "add_feedback_messages", locked)
    await dispatch(NOW)
    await dispatch(NOW + timedelta(hours=1))

    assert len(notifier.sent) == 1

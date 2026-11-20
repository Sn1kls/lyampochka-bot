import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import CopyMessages, SendMessage

from poweron.adapters.db.repository import SqlRepository
from poweron.adapters.telegram import handlers, keyboards, texts
from poweron.core.domain.models import FeedbackThread
from poweron.core.services.feedback import Feedback
from tests.telegram.test_handlers import Chat, add_address

ADMIN_CHAT_ID = 1  # the owner writes to their own bot, like in production
PHOTO = [{"file_id": "photo", "file_unique_id": "photo", "width": 1, "height": 1}]
BOT_USER = {"id": 123, "is_bot": True, "first_name": "Лямпочка"}
LATER = datetime.now(UTC) + timedelta(minutes=1)


@pytest.fixture
def chat(repository: SqlRepository) -> Chat:
    return Chat(repository, admin_chat_id=ADMIN_CHAT_ID, feedback=Feedback(repository))


def headers(chat: Chat) -> list[tuple[str, int]]:
    """Text and message id of every header sent to the admin."""
    return [
        (call.text, result.message_id)
        for call, result in zip(chat.session.calls, chat.session.results, strict=True)
        if isinstance(call, SendMessage) and call.text.startswith("✉️")
    ]


def copies(chat: Chat) -> list[tuple[list[int], list[int]]]:
    """The user's message ids of every copy, with the ids the copies got in the admin chat."""
    return [
        (call.message_ids, [copied.message_id for copied in result])
        for call, result in zip(chat.session.calls, chat.session.results, strict=True)
        if isinstance(call, CopyMessages) and result is not None
    ]


async def send_feedback(chat: Chat, message_id: int = 40, **fields: Any) -> None:
    await chat.say("/feedback")
    await chat.send(message_id=message_id, **(fields or {"text": "Графік не збігається"}))


async def reply_to(
    chat: Chat, replied_id: int, text: str | None = "Дякую, вже дивлюсь", message_id: int = 61
) -> None:
    replied = {"message_id": replied_id, "date": 0, "chat": {"id": 1, "type": "private"}}
    replied |= {"from": BOT_USER, "text": "✉️ Відгук · користувач #1"}
    fields = {"text": text} if text else {"photo": PHOTO}
    await chat.send(message_id=message_id, reply_to_message=replied, **fields)


async def test_the_admin_gets_a_copy_and_then_a_header_with_the_addresses(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.say(texts.MENU_FEEDBACK)
    assert chat.sent_texts()[-1] == texts.FEEDBACK_ASK
    await chat.send(message_id=40, text="Графік не збігається з сайтом")

    [(header, _)] = headers(chat)
    assert "#1" in header.partition("\n")[0]
    assert "Оля" in header
    assert "Руська, 5" in header
    [(copied, _)] = copies(chat)
    assert copied == [40]
    copy_call = next(
        i for i, call in enumerate(chat.session.calls) if isinstance(call, CopyMessages)
    )
    header_call = next(
        i
        for i, call in enumerate(chat.session.calls)
        if isinstance(call, SendMessage) and call.text == header
    )
    assert copy_call < header_call
    assert chat.sent_texts()[-1] == texts.FEEDBACK_SENT


async def test_feedback_is_one_message_and_then_the_bot_is_back_to_normal(chat: Chat) -> None:
    await chat.say("/start")
    await send_feedback(chat, photo=PHOTO, caption="Ось скрін")
    await chat.send(message_id=41, text="а це вже не відгук")

    assert [copied for copied, _ in copies(chat)] == [[40]]


async def test_an_album_is_one_feedback_and_its_late_parts_are_ignored(
    chat: Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handlers, "ALBUM_WAIT", 0.05)
    await chat.say("/start")
    await chat.say("/feedback")

    await asyncio.gather(
        *(
            chat.send(message_id=message_id, photo=PHOTO, media_group_id="album")
            for message_id in (52, 50, 51)
        )
    )
    await chat.say("/feedback")
    await chat.send(message_id=53, photo=PHOTO, media_group_id="album")

    assert len(headers(chat)) == 1
    assert [copied for copied, _ in copies(chat)] == [[50, 51, 52]]
    assert chat.sent_texts().count(texts.FEEDBACK_SENT) == 1


async def test_cancel_sends_nothing(chat: Chat) -> None:
    await chat.say("/start")
    await chat.say("/feedback")
    await chat.press_button(texts.BUTTON_CANCEL)
    await chat.send(message_id=40, text="передумала")

    assert chat.edited_texts()[-1] == texts.FEEDBACK_CANCELLED
    assert copies(chat) == []


async def test_a_command_while_waiting_is_run_not_forwarded(chat: Chat) -> None:
    await chat.say("/start")
    await chat.say("/feedback")
    await chat.say("/list")

    assert chat.sent_texts()[-1] == texts.NO_SUBSCRIPTIONS
    assert copies(chat) == []


async def test_over_the_limit_the_user_is_told_before_writing(repository: SqlRepository) -> None:
    chat = Chat(repository, admin_chat_id=ADMIN_CHAT_ID, feedback=Feedback(repository, limit=1))
    await chat.say("/start")
    await send_feedback(chat)

    await chat.say("/feedback")
    await chat.send(message_id=41, text="ще одне")

    assert chat.sent_texts()[-1] == texts.FEEDBACK_LIMIT.format(minutes=60)
    assert len(copies(chat)) == 1


async def test_a_message_telegram_cannot_copy_is_refused_and_not_counted(
    repository: SqlRepository,
) -> None:
    chat = Chat(repository, admin_chat_id=ADMIN_CHAT_ID, feedback=Feedback(repository, limit=1))
    await chat.say("/start")
    chat.session.uncopyable = {40}  # Telegram skips an invoice or a quiz with a hidden answer
    await send_feedback(chat)
    assert chat.sent_texts()[-1] == texts.FEEDBACK_NOT_COPYABLE
    assert headers(chat) == []

    await chat.send(message_id=41, text="тоді текстом")  # still in the feedback flow
    assert chat.sent_texts()[-1] == texts.FEEDBACK_SENT


async def test_without_an_admin_chat_feedback_is_unavailable(repository: SqlRepository) -> None:
    chat = Chat(repository, feedback=Feedback(repository))
    await chat.say("/start")
    await chat.say("/feedback")

    assert chat.sent_texts()[-1] == texts.FEEDBACK_UNAVAILABLE


async def queued(repository: SqlRepository) -> list[tuple[str, dict[str, Any]]]:
    return [
        (item.message.kind, item.message.payload)
        for item in await repository.due_messages(LATER, 10, 5)
    ]


async def test_the_admin_replies_to_the_header_or_the_copy_and_the_user_gets_both(
    chat: Chat, repository: SqlRepository
) -> None:
    await chat.say("/start")
    await send_feedback(chat)
    [(_, header_id)] = headers(chat)
    [(_, [copy_id])] = copies(chat)

    await reply_to(chat, header_id, "Дякую")
    await reply_to(chat, copy_id, "Вже виправив", message_id=62)

    assert chat.sent_texts()[-2:] == [texts.FEEDBACK_REPLY_SENT] * 2
    assert await queued(repository) == [  # both answer the user's message 40
        ("feedback_reply", {"text": "Дякую", "reply_to": 40, "answer": 61}),
        ("feedback_reply", {"text": "Вже виправив", "reply_to": 40, "answer": 62}),
    ]


async def test_a_forged_header_in_some_other_bot_message_is_not_a_feedback(
    chat: Chat, repository: SqlRepository
) -> None:
    await chat.say("/start")

    await reply_to(chat, 77)  # its text says «користувач #1», but it is not a feedback copy

    assert texts.FEEDBACK_REPLY_SENT not in chat.sent_texts()
    assert await queued(repository) == []


async def test_a_reply_to_a_bot_prompt_still_reaches_the_wizard(chat: Chat) -> None:
    await chat.say("/start")
    await chat.say("/add")
    await chat.press(keyboards.Region(provider="toe"))

    replied = {"message_id": 70, "date": 0, "chat": {"id": 1, "type": "private"}}
    replied |= {"from": BOT_USER, "text": texts.ASK_CITY}
    await chat.send(message_id=71, reply_to_message=replied, text="бережани")

    assert chat.sent_texts()[-1] == texts.ASK_STREET.format(city="Бережани")


async def test_a_reply_to_a_forgotten_user_says_so(chat: Chat) -> None:
    await chat.say("/start")
    other = await chat.subscriptions.register("telegram", "2", "telegram", "2")
    await chat.dispatcher["feedback"].record(other, 40, ["telegram:1:77"], datetime.now(UTC))
    await chat.subscriptions.forget(other)

    await reply_to(chat, 77)

    assert chat.sent_texts()[-1] == texts.FEEDBACK_USER_GONE


async def test_a_reply_that_is_not_text_or_too_long_is_refused(
    chat: Chat, repository: SqlRepository
) -> None:
    await chat.say("/start")
    await send_feedback(chat)
    [(_, header_id)] = headers(chat)

    await reply_to(chat, header_id, text=None)
    assert chat.sent_texts()[-1] == texts.FEEDBACK_REPLY_TEXT_ONLY
    await reply_to(chat, header_id, "я" * (handlers.REPLY_MAX_LENGTH + 1))
    assert chat.sent_texts()[-1] == texts.FEEDBACK_REPLY_TOO_LONG.format(
        limit=handlers.REPLY_MAX_LENGTH
    )
    assert await queued(repository) == []


async def test_a_reply_outside_the_admin_chat_is_not_an_admin_reply(
    repository: SqlRepository,
) -> None:
    chat = Chat(repository, admin_chat_id=999, feedback=Feedback(repository))
    await chat.say("/start")
    await chat.dispatcher["feedback"].record(1, 40, ["telegram:1:77"], datetime.now(UTC))

    await reply_to(chat, 77)

    assert texts.FEEDBACK_REPLY_SENT not in chat.sent_texts()
    assert await queued(repository) == []


ANSWER_ID = 61  # the admin's answer in the admin chat
DELIVERED_ID = 90  # that answer as the user got it


@pytest.fixture
def user_chat(repository: SqlRepository) -> Chat:
    """A user apart from the admin, who already got an answer to an earlier feedback."""
    return Chat(repository, admin_chat_id=999, feedback=Feedback(repository))


async def got_answer(chat: Chat, repository: SqlRepository) -> None:
    await chat.say("/start")
    await repository.add_feedback_messages(
        1, ANSWER_ID, [f"telegram:1:{DELIVERED_ID}"], datetime.now(UTC)
    )


async def reply_to_bot(
    chat: Chat, replied_id: int = DELIVERED_ID, text: str = "А тепер працює!"
) -> None:
    replied = {"message_id": replied_id, "date": 0, "chat": {"id": 1, "type": "private"}}
    replied |= {"from": BOT_USER, "text": "💬 Відповідь розробника\n\nВиправив, перевір"}
    await chat.send(message_id=91, reply_to_message=replied, text=text)


def header_replies(chat: Chat) -> list[int | None]:
    """Which admin message each header answers, if any."""
    return [
        call.reply_parameters.message_id if call.reply_parameters else None
        for call in chat.session.calls
        if isinstance(call, SendMessage) and call.text.startswith("✉️")
    ]


async def test_the_users_reply_to_an_answer_is_a_feedback_replying_to_that_answer(
    user_chat: Chat, repository: SqlRepository
) -> None:
    await got_answer(user_chat, repository)

    await reply_to_bot(user_chat)

    assert [copied for copied, _ in copies(user_chat)] == [[91]]
    assert header_replies(user_chat) == [ANSWER_ID]
    assert user_chat.sent_texts()[-1] == texts.FEEDBACK_SENT


async def test_a_plain_feedback_header_replies_to_nothing(chat: Chat) -> None:
    await chat.say("/start")
    await send_feedback(chat)

    assert header_replies(chat) == [None]


async def test_the_reply_to_an_answer_keeps_the_limit(repository: SqlRepository) -> None:
    chat = Chat(repository, admin_chat_id=999, feedback=Feedback(repository, limit=1))
    await got_answer(chat, repository)
    await send_feedback(chat)

    await reply_to_bot(chat)

    assert chat.sent_texts()[-1] == texts.FEEDBACK_LIMIT.format(minutes=60)
    assert len(copies(chat)) == 1


async def test_a_reply_to_another_bot_message_is_not_a_feedback(
    user_chat: Chat, repository: SqlRepository
) -> None:
    await got_answer(user_chat, repository)

    await reply_to_bot(user_chat, replied_id=77)  # looks like an answer, but is not one

    assert copies(user_chat) == []


async def test_a_command_sent_as_a_reply_to_an_answer_runs(
    user_chat: Chat, repository: SqlRepository
) -> None:
    await got_answer(user_chat, repository)

    await reply_to_bot(user_chat, text="/add")

    assert user_chat.sent_texts()[-1] == texts.ASK_REGION
    assert copies(user_chat) == []


async def test_a_reply_to_an_answer_mid_wizard_is_the_wizard_answer(
    user_chat: Chat, repository: SqlRepository
) -> None:
    await got_answer(user_chat, repository)
    await user_chat.say("/add")
    await user_chat.press(keyboards.Region(provider="toe"))

    await reply_to_bot(user_chat, text="бережани")

    assert user_chat.sent_texts()[-1] == texts.ASK_STREET.format(city="Бережани")
    assert copies(user_chat) == []


async def test_an_album_sent_as_a_reply_to_an_answer_is_one_feedback(
    user_chat: Chat, repository: SqlRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(handlers, "ALBUM_WAIT", 0.05)
    await got_answer(user_chat, repository)
    replied = {"message_id": DELIVERED_ID, "date": 0, "chat": {"id": 1, "type": "private"}}
    replied |= {"from": BOT_USER, "text": "💬 Відповідь розробника\n\nДякую"}

    await asyncio.gather(
        *(
            user_chat.send(
                message_id=message_id,
                photo=PHOTO,
                media_group_id="reply-album",
                reply_to_message=replied,
            )
            for message_id in (93, 92)
        )
    )

    assert [copied for copied, _ in copies(user_chat)] == [[92, 93]]


async def test_an_unreachable_admin_chat_makes_feedback_unavailable(chat: Chat) -> None:
    await chat.say("/start")
    chat.session.errors[CopyMessages] = TelegramBadRequest(
        CopyMessages(chat_id=1, from_chat_id=1, message_ids=[40]), "Bad Request: chat not found"
    )

    await send_feedback(chat)
    await chat.send(message_id=41, text="ще раз")  # not stuck in the feedback flow

    assert chat.sent_texts()[-1] == texts.FEEDBACK_UNAVAILABLE
    assert chat.sent_texts().count(texts.FEEDBACK_UNAVAILABLE) == 1


async def test_without_the_header_the_copy_still_leads_back_to_the_user(
    user_chat: Chat, repository: SqlRepository
) -> None:
    await user_chat.say("/start")
    user_chat.session.failing_chats = {999}  # Telegram refuses the header, e.g. a flood limit

    await send_feedback(user_chat)

    [(_, [copy_id])] = copies(user_chat)
    feedback = user_chat.dispatcher["feedback"]
    assert await feedback.thread(f"telegram:999:{copy_id}") == FeedbackThread(1, 40)
    assert user_chat.sent_texts()[-1] == texts.FEEDBACK_SENT

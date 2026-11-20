import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import CopyMessages, SendMessage

from poweron.adapters.db.repository import SqlRepository
from poweron.adapters.telegram import handlers, keyboards, texts
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
    chat.session.errors[CopyMessages] = TelegramBadRequest(
        CopyMessages(chat_id=1, from_chat_id=1, message_ids=[40]),
        "Bad Request: message can't be copied",
    )
    await send_feedback(chat)
    assert chat.sent_texts()[-1] == texts.FEEDBACK_NOT_COPYABLE
    assert headers(chat) == []

    del chat.session.errors[CopyMessages]
    await send_feedback(chat, message_id=41)
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
    assert await queued(repository) == [
        ("feedback_reply", {"text": "Дякую"}),
        ("feedback_reply", {"text": "Вже виправив"}),
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
    await chat.dispatcher["feedback"].received(other, ["telegram:1:77"], datetime.now(UTC))
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
    await chat.dispatcher["feedback"].received(1, ["telegram:1:77"], datetime.now(UTC))

    await reply_to(chat, 77)

    assert texts.FEEDBACK_REPLY_SENT not in chat.sent_texts()
    assert await queued(repository) == []

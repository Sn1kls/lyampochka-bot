import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from aiogram.methods import CopyMessages, SendMessage

from poweron.adapters.db.repository import SqlRepository
from poweron.adapters.telegram import handlers, texts
from poweron.core.services.feedback import Feedback
from tests.telegram.test_handlers import Chat, add_address

ADMIN_CHAT_ID = 1  # the owner writes to their own bot, like in production
PHOTO = [{"file_id": "photo", "file_unique_id": "photo", "width": 1, "height": 1}]
BOT_USER = {"id": 123, "is_bot": True, "first_name": "Лямпочка"}


@pytest.fixture
def chat(repository: SqlRepository) -> Chat:
    return Chat(repository, admin_chat_id=ADMIN_CHAT_ID, feedback=Feedback(repository))


def to_admin(chat: Chat) -> list[str]:
    return [
        call.text
        for call in chat.session.calls
        if isinstance(call, SendMessage) and call.text.startswith("✉️")
    ]


def copies(chat: Chat) -> list[list[int]]:
    return [call.message_ids for call in chat.session.calls if isinstance(call, CopyMessages)]


async def test_a_text_reaches_the_admin_under_a_header_with_the_addresses(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.say(texts.MENU_FEEDBACK)
    assert chat.sent_texts()[-1] == texts.FEEDBACK_ASK
    await chat.send(message_id=40, text="Графік не збігається з сайтом")

    [header] = to_admin(chat)
    assert "#1" in header.partition("\n")[0]
    assert "Оля" in header
    assert "Руська, 5" in header
    assert copies(chat) == [[40]]
    assert chat.sent_texts()[-1] == texts.FEEDBACK_SENT


async def test_feedback_is_one_message_and_then_the_bot_is_back_to_normal(chat: Chat) -> None:
    await chat.say("/start")
    await chat.say("/feedback")
    await chat.send(message_id=40, photo=PHOTO, caption="Ось скрін")
    await chat.send(message_id=41, text="а це вже не відгук")

    assert copies(chat) == [[40]]


async def test_an_album_is_one_feedback(chat: Chat, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "ALBUM_WAIT", 0.05)
    await chat.say("/start")
    await chat.say("/feedback")

    await asyncio.gather(
        *(
            chat.send(message_id=message_id, photo=PHOTO, media_group_id="album")
            for message_id in (52, 50, 51)
        )
    )

    assert len(to_admin(chat)) == 1
    assert copies(chat) == [[50, 51, 52]]
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


async def test_over_the_limit_nothing_is_forwarded(repository: SqlRepository) -> None:
    chat = Chat(repository, admin_chat_id=ADMIN_CHAT_ID, feedback=Feedback(repository, limit=1))
    await chat.say("/start")
    for message_id in (40, 41):
        await chat.say("/feedback")
        await chat.send(message_id=message_id, text="ще одне")

    assert copies(chat) == [[40]]
    assert chat.sent_texts()[-1] == texts.FEEDBACK_LIMIT.format(minutes=60)


async def test_without_an_admin_chat_feedback_is_unavailable(repository: SqlRepository) -> None:
    chat = Chat(repository, feedback=Feedback(repository))
    await chat.say("/start")
    await chat.say("/feedback")

    assert chat.sent_texts()[-1] == texts.FEEDBACK_UNAVAILABLE


async def reply_to(chat: Chat, replied_text: str, text: str | None = "Дякую, вже дивлюсь") -> None:
    replied = {"message_id": 60, "date": 0, "chat": {"id": 1, "type": "private"}}
    replied |= {"from": BOT_USER, "text": replied_text}
    fields = {"text": text} if text else {"photo": PHOTO}
    await chat.send(message_id=61, reply_to_message=replied, **fields)


async def test_the_admin_replies_to_the_header_and_the_user_gets_it(
    chat: Chat, repository: SqlRepository
) -> None:
    await chat.say("/start")
    await chat.say("/feedback")
    await chat.send(message_id=40, text="Графік не збігається")
    [header] = to_admin(chat)

    await reply_to(chat, header)

    assert chat.sent_texts()[-1] == texts.FEEDBACK_REPLY_SENT
    [queued] = await repository.due_messages(datetime.now(UTC) + timedelta(minutes=1), 10, 5)
    assert (queued.message.kind, queued.message.payload) == (
        "feedback_reply",
        {"text": "Дякую, вже дивлюсь"},
    )


async def test_a_reply_to_a_gone_user_says_so(chat: Chat) -> None:
    await chat.say("/start")

    await reply_to(chat, "✉️ Відгук · користувач #999\nХтось")

    assert chat.sent_texts()[-1] == texts.FEEDBACK_USER_GONE


async def test_a_reply_without_a_header_gets_a_hint(chat: Chat) -> None:
    await chat.say("/start")

    await reply_to(chat, "💡 Графік на сьогодні")

    assert chat.sent_texts()[-1] == texts.FEEDBACK_REPLY_HINT


async def test_a_reply_that_is_not_text_is_refused(chat: Chat) -> None:
    await chat.say("/start")

    await reply_to(chat, "✉️ Відгук · користувач #1\nОля", text=None)

    assert chat.sent_texts()[-1] == texts.FEEDBACK_REPLY_TEXT_ONLY


async def test_a_reply_outside_the_admin_chat_is_not_an_admin_reply(
    repository: SqlRepository,
) -> None:
    chat = Chat(repository, admin_chat_id=999, feedback=Feedback(repository))
    await chat.say("/start")

    await reply_to(chat, "✉️ Відгук · користувач #1\nОля")

    assert texts.FEEDBACK_REPLY_SENT not in chat.sent_texts()
    assert texts.FEEDBACK_REPLY_HINT not in chat.sent_texts()
    assert await repository.due_messages(datetime.now(UTC) + timedelta(minutes=1), 10, 5) == []

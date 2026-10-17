from collections.abc import AsyncGenerator
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import Update

from poweron.adapters.db.repository import SqlRepository
from poweron.adapters.telegram import keyboards, texts
from poweron.adapters.telegram.bot import build_dispatcher
from poweron.core.domain.models import Building, City, Street
from poweron.core.services.catalog import Catalog
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions

USER = {"id": 1, "is_bot": False, "first_name": "Оля"}
CHAT = {"id": 1, "type": "private"}
CITIES = [
    City(1, "Тернопіль", None),
    City(2, "Нова Тернопільська", None),
    City(3, "Бережани", None),
]


class FakeCatalogSource:
    async def cities(self) -> list[City]:
        return CITIES

    async def streets(self, city_id: int) -> list[Street]:
        return []

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        return []


class RecordingSession(BaseSession):
    """Records bot API calls instead of sending them; `errors` makes a method type fail."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self.errors: dict[type[TelegramMethod[Any]], Exception] = {}

    async def close(self) -> None:
        pass

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[Any],
        timeout: int | None = None,  # noqa: ASYNC109 (signature of BaseSession)
    ) -> Any:
        self.calls.append(method)
        if type(method) in self.errors:
            raise self.errors[type(method)]
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes]:
        yield b""


class Chat:
    def __init__(self, repository: SqlRepository) -> None:
        self.subscriptions = Subscriptions(repository)
        self.session = RecordingSession()
        self.bot = Bot("123:abc", session=self.session)
        self.dispatcher: Dispatcher = build_dispatcher(
            self.subscriptions,
            Catalog(repository, FakeCatalogSource()),
            Schedules(repository),
        )
        self._update_id = 0

    async def say(self, text: str) -> None:
        entities = [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]
        message = {
            "message_id": 1,
            "date": 0,
            "chat": CHAT,
            "from": USER,
            "text": text,
            "entities": entities if text.startswith("/") else [],
        }
        await self._feed({"message": message})

    async def press(self, callback_data: keyboards.CallbackData) -> None:
        message = {"message_id": 1, "date": 0, "chat": CHAT, "text": "list"}
        callback = {
            "id": "1",
            "from": USER,
            "chat_instance": "x",
            "message": message,
            "data": callback_data.pack(),
        }
        await self._feed({"callback_query": callback})

    async def _feed(self, payload: dict[str, Any]) -> None:
        self._update_id += 1
        update = Update.model_validate(
            {"update_id": self._update_id, **payload}, context={"bot": self.bot}
        )
        await self.dispatcher.feed_update(self.bot, update)

    def sent_texts(self) -> list[str]:
        return [call.text for call in self.session.calls if isinstance(call, SendMessage)]

    def edited_texts(self) -> list[str]:
        return [call.text for call in self.session.calls if isinstance(call, EditMessageText)]

    def alerts(self) -> list[str | None]:
        return [
            call.text
            for call in self.session.calls
            if isinstance(call, AnswerCallbackQuery) and call.show_alert
        ]


@pytest.fixture
def chat(repository: SqlRepository) -> Chat:
    return Chat(repository)


async def test_unknown_user_is_asked_to_start_and_not_registered(chat: Chat) -> None:
    await chat.say("/list")

    assert chat.sent_texts() == [texts.START_FIRST]
    assert await chat.subscriptions.find_user("telegram", "1") is None


async def test_unknown_user_pressing_a_button_gets_an_alert(chat: Chat) -> None:
    await chat.press(keyboards.DayChoice(subscription_id=1, offset=0))

    assert chat.alerts() == [texts.START_FIRST]
    assert await chat.subscriptions.find_user("telegram", "1") is None


async def test_start_registers_the_user_and_unlocks_commands(chat: Chat) -> None:
    await chat.say("/start")
    await chat.say("/list")

    assert chat.sent_texts() == [texts.GREETING, texts.NO_SUBSCRIPTIONS]
    assert await chat.subscriptions.find_user("telegram", "1") is not None


async def test_stale_button_does_not_bring_a_forgotten_user_back(chat: Chat) -> None:
    await chat.say("/start")
    await chat.press(keyboards.Decision(action="forget", accepted=True))
    await chat.press(keyboards.Decision(action="forget", accepted=False))

    assert chat.alerts() == [texts.START_FIRST]
    assert await chat.subscriptions.find_user("telegram", "1") is None


async def start_city_search(chat: Chat, *queries: str) -> None:
    await chat.say("/start")
    await chat.say("/add")
    for query in queries:
        await chat.say(query)


async def test_button_of_an_older_search_is_stale(chat: Chat) -> None:
    await start_city_search(chat, "тер", "бер")

    await chat.press(keyboards.Pick(kind="city", index=0, generation=1))

    assert chat.alerts() == [texts.STALE_BUTTON]
    assert chat.edited_texts() == []
    await chat.press(keyboards.Pick(kind="city", index=0, generation=2))
    assert "Бережани" in chat.edited_texts()[0]


async def test_page_button_of_an_older_search_is_stale(chat: Chat) -> None:
    await start_city_search(chat, "тер", "бер")

    await chat.press(keyboards.Page(kind="city", number=1, generation=1))

    assert chat.alerts() == [texts.STALE_BUTTON]


async def test_button_index_outside_the_list_is_stale(chat: Chat) -> None:
    await start_city_search(chat, "тер")

    await chat.press(keyboards.Pick(kind="city", index=7, generation=1))

    assert chat.alerts() == [texts.STALE_BUTTON]


async def test_buttons_of_a_finished_wizard_do_not_match_the_next_one(chat: Chat) -> None:
    await start_city_search(chat, "тер")
    await chat.say("/add")
    await chat.say("бер")

    await chat.press(keyboards.Pick(kind="city", index=0, generation=1))

    assert chat.alerts() == [texts.STALE_BUTTON]


async def test_pressing_a_button_twice_ignores_the_unmodified_message(chat: Chat) -> None:
    await start_city_search(chat, "бер")
    chat.session.errors[EditMessageText] = TelegramBadRequest(
        EditMessageText(text="x"), "Bad Request: message is not modified"
    )

    await chat.press(keyboards.Pick(kind="city", index=0, generation=1))


async def test_other_telegram_errors_are_not_swallowed(chat: Chat) -> None:
    await start_city_search(chat, "бер")
    chat.session.errors[EditMessageText] = TelegramBadRequest(
        EditMessageText(text="x"), "Bad Request: can't parse entities"
    )

    with pytest.raises(TelegramBadRequest):
        await chat.press(keyboards.Pick(kind="city", index=0, generation=1))

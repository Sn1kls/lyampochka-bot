from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import AnswerCallbackQuery, EditMessageText, SendMessage, TelegramMethod
from aiogram.types import (
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)

from poweron.adapters.db.repository import SqlRepository
from poweron.adapters.telegram import keyboards, texts
from poweron.adapters.telegram.bot import build_dispatcher
from poweron.core.domain.diff import data_hash
from poweron.core.domain.models import Building, City, ScheduleVersion, Street, Subscription
from poweron.core.services.catalog import Catalog
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions

USER = {"id": 1, "is_bot": False, "first_name": "Оля"}
CHAT = {"id": 1, "type": "private"}
CITIES = [
    City(1, "Тернопіль", None),
    City(2, "Нова Тернопільська", None),
    City(3, "Бережани", None),
    City(4, "Бережанка", None),
]


class FakeCatalogSource:
    async def cities(self) -> list[City]:
        return CITIES

    async def streets(self, city_id: int) -> list[Street]:
        return [Street(1, "вул. Руська")]

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        return [Building(1, "5", "4.1"), Building(2, "96", "4.1")]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        return ["2.2", "4.1"] if building_name == "96" else ["4.1"]


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


class SettingsSubscriptions(Subscriptions):
    """Core's update_settings is not implemented in this worktree; this keeps changes in memory."""

    def __init__(self, repository: SqlRepository) -> None:
        super().__init__(repository)
        self.stored: dict[int, dict[str, Any]] = {}

    async def update_settings(
        self,
        user_id: int,
        subscription_id: int,
        *,
        notify_on_update: bool | None = None,
        remind_before_off_min: int | None = None,
        remind_before_on_min: int | None = None,
    ) -> Subscription | None:
        subscription = await self.get(user_id, subscription_id)
        if subscription is None:
            return None
        given = {
            "notify_on_update": notify_on_update,
            "remind_before_off_min": remind_before_off_min,
            "remind_before_on_min": remind_before_on_min,
        }
        self.stored.setdefault(subscription_id, {}).update(
            {name: value for name, value in given.items() if value is not None}
        )
        return replace(subscription, **self.stored[subscription_id])


class Chat:
    def __init__(self, repository: SqlRepository) -> None:
        self.subscriptions = SettingsSubscriptions(repository)
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

    async def press_button(self, text: str) -> None:
        """Presses the inline button with this text on the last message that had buttons."""
        markup = [
            call.reply_markup
            for call in self.session.calls
            if isinstance(call, SendMessage | EditMessageText)
            and isinstance(call.reply_markup, InlineKeyboardMarkup)
        ][-1]
        [button] = [b for row in markup.inline_keyboard for b in row if b.text == text]
        message = {"message_id": 1, "date": 0, "chat": CHAT, "text": "x"}
        callback = {
            "id": "1",
            "from": USER,
            "chat_instance": "x",
            "message": message,
            "data": button.callback_data,
        }
        await self._feed({"callback_query": callback})

    def last_reply_markup(self) -> Any:
        return [call for call in self.session.calls if isinstance(call, SendMessage)][
            -1
        ].reply_markup

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


async def test_a_single_search_result_is_chosen_without_a_button(chat: Chat) -> None:
    await start_city_search(chat, "бережани")

    assert chat.sent_texts()[-1] == texts.ASK_STREET.format(city="Бережани")


async def test_a_partial_single_match_still_asks_to_confirm(chat: Chat) -> None:
    await start_city_search(chat, "ережани")

    assert chat.sent_texts()[-1] == texts.CHOOSE_CITY


async def add_address(chat: Chat, building: str) -> None:
    await start_city_search(chat, "бережани", "руська", building)


async def test_start_and_a_finished_add_show_the_phone_menu(chat: Chat) -> None:
    await chat.say("/start")
    markup = chat.last_reply_markup()
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.is_persistent and markup.resize_keyboard
    assert [[button.text for button in row] for row in markup.keyboard] == [
        ["📅 Графік", "⏭ Що далі"],
        ["📋 Мої адреси", "➕ Додати адресу"],
        ["⚙️ Налаштування", "🗑 Видалити адресу"],
        ["❓ Допомога"],
    ]

    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    assert chat.sent_texts()[-1] == texts.ADDED.format(label="Дім")
    assert isinstance(chat.last_reply_markup(), ReplyKeyboardMarkup)


async def test_remove_and_cancelled_forget_show_the_menu_and_forget_removes_it(
    chat: Chat,
) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.say("/remove")
    await chat.press_button("Дім")
    assert chat.sent_texts()[-1] == texts.REMOVED
    assert isinstance(chat.last_reply_markup(), ReplyKeyboardMarkup)

    await chat.say("/forget")
    await chat.press_button(texts.BUTTON_CANCEL)
    assert chat.sent_texts()[-1] == texts.CANCELLED
    assert isinstance(chat.last_reply_markup(), ReplyKeyboardMarkup)

    await chat.say("/forget")
    await chat.press_button(texts.BUTTON_FORGET)
    assert chat.sent_texts()[-1] == texts.FORGOTTEN
    assert isinstance(chat.last_reply_markup(), ReplyKeyboardRemove)


@pytest.mark.parametrize(
    ("button", "command"),
    [
        (texts.MENU_SCHEDULE, "/schedule"),
        (texts.MENU_NEXT, "/next"),
        (texts.MENU_LIST, "/list"),
        (texts.MENU_ADD, "/add"),
        (texts.MENU_SETTINGS, "/settings"),
        (texts.MENU_REMOVE, "/remove"),
        (texts.MENU_HELP, "/help"),
    ],
)
async def test_each_menu_button_runs_the_command_handler(
    chat: Chat, button: str, command: str
) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.say(command)
    await chat.say(button)

    *_, by_command, by_button = chat.sent_texts()
    assert by_button == by_command


@pytest.mark.parametrize("button", [texts.MENU_SCHEDULE, texts.MENU_SETTINGS])
async def test_menu_button_in_the_middle_of_the_wizard_leaves_it(chat: Chat, button: str) -> None:
    await chat.say("/start")
    await chat.say("/add")
    await chat.say("бережани")
    assert chat.sent_texts()[-1] == texts.ASK_STREET.format(city="Бережани")

    await chat.say(button)
    assert chat.sent_texts()[-1] == texts.NO_SUBSCRIPTIONS

    sent_before = len(chat.sent_texts())
    await chat.say("руська")  # would be the street search if the wizard were still open
    assert len(chat.sent_texts()) == sent_before


async def test_single_queue_building_skips_the_queue_choice(chat: Chat) -> None:
    await add_address(chat, "5")

    assert "Підчерга 4.1" in chat.sent_texts()[-1]


async def test_building_in_several_queues_asks_which_to_track(chat: Chat) -> None:
    await add_address(chat, "96")
    assert chat.sent_texts()[-1] == texts.CHOOSE_QUEUES.format(queues="2.2, 4.1")

    await chat.press_button("Черга 2.2")
    assert "Черги 2.2 (стежу), 4.1" in chat.edited_texts()[-1]
    await chat.press_button(texts.BUTTON_SAVE)

    [subscription] = await chat.subscriptions.of_user(1)
    assert subscription.tracked_subqueues == ("2.2",)
    assert subscription.subqueues == ("2.2", "4.1")


async def test_all_queues_choice_tracks_every_queue(chat: Chat) -> None:
    await add_address(chat, "96")

    await chat.press_button(texts.BUTTON_ALL_QUEUES)
    assert "Черги 2.2 і 4.1" in chat.edited_texts()[-1]
    await chat.press_button(texts.BUTTON_SAVE)

    [subscription] = await chat.subscriptions.of_user(1)
    assert subscription.tracked_subqueues == ("2.2", "4.1")


async def test_untracked_queue_can_be_viewed_with_its_button(
    chat: Chat, repository: SqlRepository
) -> None:
    await add_address(chat, "96")
    await chat.press_button("Черга 2.2")
    await chat.press_button(texts.BUTTON_SAVE)
    now = datetime.now(UTC)
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    for queue in ("2.2", "4.1"):
        version = ScheduleVersion(queue, now.date(), now, data_hash(slots), slots, now)
        await repository.save_version(version, [])

    await chat.say("/schedule")
    await chat.press_button(texts.TODAY)
    assert "Підчерга 2.2" in chat.edited_texts()[-1]

    await chat.press_button("Черга 4.1")
    assert "Підчерга 4.1" in chat.edited_texts()[-1]
    assert "Підчерга 2.2" not in chat.edited_texts()[-1]


def button_texts(markup: Any) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


async def test_settings_shows_the_state_and_each_press_edits_the_same_message(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.say("/settings")

    assert chat.sent_texts()[-1] == "\n".join(
        [
            "⚙️ Налаштування для <b>Дім</b>",
            "Пуші про оновлення графіка: увімкнено",
            "⏰ Нагадати перед вимкненням: 30 хв",
            "💡 Нагадати перед поверненням світла: без",
        ]
    )
    assert button_texts(chat.last_reply_markup()) == [
        ["✅ Пуші про оновлення"],
        ["⏰ Нагадати до вимкнення: 30 хв"],
        ["💡 Нагадати до повернення: без"],
    ]

    await chat.press_button("✅ Пуші про оновлення")
    await chat.press_button("⏰ Нагадати до вимкнення: 30 хв")
    await chat.press_button("💡 Нагадати до повернення: без")

    assert chat.subscriptions.stored == {
        1: {"notify_on_update": False, "remind_before_off_min": 60, "remind_before_on_min": 15}
    }
    assert chat.edited_texts()[-1].splitlines()[1:] == [
        "Пуші про оновлення графіка: вимкнено",
        "⏰ Нагадати перед вимкненням: 60 хв",
        "💡 Нагадати перед поверненням світла: 15 хв",
    ]
    edited_markup = [call for call in chat.session.calls if isinstance(call, EditMessageText)][
        -1
    ].reply_markup
    assert button_texts(edited_markup) == [
        ["🚫 Пуші про оновлення"],
        ["⏰ Нагадати до вимкнення: 60 хв"],
        ["💡 Нагадати до повернення: 15 хв"],
    ]


async def test_settings_of_an_address_chosen_from_several(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.press(keyboards.SubscriptionChoice(action="settings", subscription_id=1))

    assert chat.edited_texts()[-1].startswith("⚙️ Налаштування для <b>Дім</b>")


async def test_setting_of_a_missing_address_is_reported_and_stores_nothing(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.press(
        keyboards.SettingChange(subscription_id=99, field="remind_before_off_min", value=15)
    )

    assert chat.edited_texts()[-1] == texts.ADDRESS_GONE
    assert chat.subscriptions.stored == {}


@pytest.mark.parametrize(
    ("field", "value"),
    [("remind_before_off_min", 45), ("notify_on_update", 2), ("label", 1)],
)
async def test_unknown_setting_is_a_stale_button(chat: Chat, field: str, value: int) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)

    await chat.press(keyboards.SettingChange(subscription_id=1, field=field, value=value))

    assert chat.alerts() == [texts.STALE_BUTTON]
    assert chat.subscriptions.stored == {}


async def test_pressing_the_same_setting_twice_ignores_the_unmodified_message(chat: Chat) -> None:
    await add_address(chat, "5")
    await chat.press_button(texts.BUTTON_SAVE)
    chat.session.errors[EditMessageText] = TelegramBadRequest(
        EditMessageText(text="x"), "Bad Request: message is not modified"
    )

    await chat.press(
        keyboards.SettingChange(subscription_id=1, field="remind_before_on_min", value=0)
    )

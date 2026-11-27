import asyncio
from itertools import pairwise
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramServerError
from aiogram.methods import SendMessage
from aiogram.types import ReplyKeyboardMarkup, ReplyParameters

from poweron.adapters.telegram import keyboards, texts
from poweron.adapters.telegram.notifier import TelegramNotifier
from poweron.core.ports import DeliveryTargetGone

PAYLOAD = {
    "cherg_gpv": "4.1",
    "day": "2026-10-17",
    "label": "Дім",
    "previous": None,
    "current": [],
    "added": [],
    "removed": [],
}
METHOD = SendMessage(chat_id=1, text="x")


class FakeBot:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[tuple[int, str]] = []
        self.markups: list[object] = []
        self.silent: list[bool | None] = []
        self.replies_to: list[ReplyParameters | None] = []
        self.send_times: list[float] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: object = None,
        disable_notification: bool | None = None,
        reply_parameters: ReplyParameters | None = None,
    ) -> SimpleNamespace:
        self.send_times.append(asyncio.get_running_loop().time())
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text))
        self.markups.append(reply_markup)
        self.silent.append(disable_notification)
        self.replies_to.append(reply_parameters)
        return SimpleNamespace(message_id=500)


def notifier_with(bot: FakeBot) -> TelegramNotifier:
    return TelegramNotifier(bot)  # type: ignore[arg-type]


async def test_sends_rendered_update() -> None:
    bot = FakeBot()

    await notifier_with(bot).send("42", "schedule_updated", PAYLOAD)

    chat_id, text = bot.sent[0]
    assert chat_id == 42
    assert text.splitlines()[0].startswith("💡 Оновлення на ")


@pytest.mark.parametrize(
    "error",
    [
        TelegramForbiddenError(METHOD, "Forbidden: bot was blocked by the user"),
        TelegramBadRequest(METHOD, "Bad Request: chat not found"),
    ],
)
async def test_gone_chat_becomes_delivery_target_gone(error: Exception) -> None:
    with pytest.raises(DeliveryTargetGone):
        await notifier_with(FakeBot(error)).send("42", "schedule_updated", PAYLOAD)


@pytest.mark.parametrize(
    "error",
    [
        TelegramBadRequest(METHOD, "Bad Request: can't parse entities"),
        TelegramServerError(METHOD, "Bad Gateway"),
    ],
)
async def test_other_errors_propagate_for_retry(error: Exception) -> None:
    with pytest.raises(type(error)):
        await notifier_with(FakeBot(error)).send("42", "schedule_updated", PAYLOAD)


REMINDER = {
    "subscription_id": 1,
    "label": "Дім",
    "cherg_gpv": "4.1#7",
    "queue_count": 1,
    "minutes": 15,
    "earliest": "2026-10-17T07:00:00+00:00",
    "latest": "2026-10-17T07:30:00+00:00",
}
SUBQUEUES = {
    "subscription_id": 1,
    "label": "Дім",
    "previous": ["4.1#7"],
    "current": ["2.2#3", "4.1#7"],
    "tracked": ["4.1#7"],
}
PLANNED_WORK = {
    "subscription_id": 1,
    "label": "Дім",
    "starts_at": "2026-08-22T05:30:00+00:00",
    "ends_at": "2026-08-22T14:30:00+00:00",
    "reason": "Ремонт ПЛ",
}


@pytest.mark.parametrize(
    ("kind", "payload", "start"),
    [
        ("reminder_off", REMINDER, "🪫 За 15 хв можуть ВИМКНУТИ світло"),
        ("reminder_on", REMINDER, "🔋 За 15 хв мають ДАТИ світло"),
        ("subqueues_changed", SUBQUEUES, "🔄 Для <b>Дім</b> змінилися черги."),
        ("planned_work", PLANNED_WORK, "🛠 <b>Дім</b>: планові роботи 22.08 з 08:30 до 17:30"),
    ],
)
async def test_new_kinds_are_rendered_and_sent(
    kind: str, payload: dict[str, object], start: str
) -> None:
    bot = FakeBot()

    await notifier_with(bot).send("42", kind, payload)

    assert bot.sent[0][1].startswith(start)


async def test_menu_update_brings_the_new_keyboard() -> None:
    bot = FakeBot()

    await notifier_with(bot).send("42", "menu_updated", {})

    assert bot.sent == [(42, texts.MENU_UPDATED)]
    assert isinstance(bot.markups[0], ReplyKeyboardMarkup)
    assert bot.silent == [True]  # news about the menu is not worth a buzz


async def test_a_user_without_an_address_is_nudged_with_a_buzz() -> None:
    bot = FakeBot()
    await notifier_with(bot).send("42", "no_address", {})

    assert bot.sent == [(42, texts.NO_ADDRESS_NUDGE)]
    assert bot.silent == [None]
    # The add button rides on the message: the reply keyboard has none.
    assert bot.markups == [keyboards.actions_keyboard("add")]


async def test_every_push_refreshes_the_menu_without_a_separate_announcement() -> None:
    bot = FakeBot()

    await notifier_with(bot).send("42", "schedule_updated", PAYLOAD)

    assert isinstance(bot.markups[0], ReplyKeyboardMarkup)
    assert bot.silent == [None]
    assert bot.replies_to == [None]


async def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        await notifier_with(FakeBot()).send("42", "reminder", PAYLOAD)


async def test_concurrent_sends_are_spaced() -> None:
    bot = FakeBot()
    notifier = notifier_with(bot)

    await asyncio.gather(*(notifier.send("42", "schedule_updated", PAYLOAD) for _ in range(4)))

    gaps = [later - earlier for earlier, later in pairwise(bot.send_times)]
    assert all(gap >= 0.035 for gap in gaps)


async def test_the_developer_reply_is_shown_as_plain_text() -> None:
    bot = FakeBot()

    payload = {"text": "Дякую! <b>не жирний</b>", "reply_to": 40, "answer": 61}
    delivered = await notifier_with(bot).send("42", "feedback_reply", payload)

    assert bot.sent == [
        (42, texts.FEEDBACK_REPLY.format(text="Дякую! &lt;b&gt;не жирний&lt;/b&gt;"))
    ]
    # Quotes the user's feedback, and still arrives if they deleted it.
    assert bot.replies_to == [ReplyParameters(message_id=40, allow_sending_without_reply=True)]
    assert delivered == "telegram:42:500"  # so a Reply to it can be traced back

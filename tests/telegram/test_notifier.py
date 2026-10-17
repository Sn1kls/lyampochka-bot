import asyncio
from itertools import pairwise
from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramServerError
from aiogram.methods import SendMessage

from poweron.adapters.telegram.notifier import TelegramNotifier
from poweron.core.ports import DeliveryTargetGone

PAYLOAD = {
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
        self.sent: list[tuple[int, str, dict[str, Any]]] = []
        self.send_times: list[float] = []

    async def send_message(self, chat_id: int, text: str, **options: Any) -> None:
        self.send_times.append(asyncio.get_running_loop().time())
        if self.error is not None:
            raise self.error
        self.sent.append((chat_id, text, options))


def notifier_with(bot: FakeBot) -> TelegramNotifier:
    return TelegramNotifier(bot)  # type: ignore[arg-type]


async def test_sends_rendered_update_without_link_preview() -> None:
    bot = FakeBot()

    await notifier_with(bot).send("42", "schedule_updated", PAYLOAD)

    chat_id, text, options = bot.sent[0]
    assert chat_id == 42
    assert text.startswith("💡 Графік для <b>Дім</b> оновлено")
    assert options["link_preview_options"].is_disabled is True


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


async def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ValueError):
        await notifier_with(FakeBot()).send("42", "reminder", PAYLOAD)


async def test_concurrent_sends_are_spaced() -> None:
    bot = FakeBot()
    notifier = notifier_with(bot)

    await asyncio.gather(*(notifier.send("42", "schedule_updated", PAYLOAD) for _ in range(4)))

    gaps = [later - earlier for earlier, later in pairwise(bot.send_times)]
    assert all(gap >= 0.035 for gap in gaps)

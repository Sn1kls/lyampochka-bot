import asyncio
from collections.abc import Mapping
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from poweron.core.domain.models import MessageKind
from poweron.core.ports import DeliveryTargetGone

from .render import render_reminder, render_subqueues_changed, render_update

SEND_INTERVAL = 0.04
CHAT_GONE_MARKERS = ("chat not found", "user not found")


def _render(kind: str, payload: Mapping[str, Any]) -> str:
    match kind:
        case MessageKind.SCHEDULE_UPDATED:
            return render_update(payload)
        case MessageKind.REMINDER_OFF:
            return render_reminder(payload, power_on=False)
        case MessageKind.REMINDER_ON:
            return render_reminder(payload, power_on=True)
        case MessageKind.SUBQUEUES_CHANGED:
            return render_subqueues_changed(payload)
        case _:
            raise ValueError(f"unknown message kind {kind!r}")


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._slot_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> None:
        text = _render(kind, payload)
        await self._wait_for_slot()
        try:
            await self._bot.send_message(int(address), text)
        except TelegramForbiddenError as error:
            raise DeliveryTargetGone(address) from error
        except TelegramBadRequest as error:
            if any(marker in error.message.lower() for marker in CHAT_GONE_MARKERS):
                raise DeliveryTargetGone(address) from error
            raise

    async def _wait_for_slot(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._slot_lock:
            await asyncio.sleep(max(0.0, self._next_slot - loop.time()))
            self._next_slot = loop.time() + SEND_INTERVAL

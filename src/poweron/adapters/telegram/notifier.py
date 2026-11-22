import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import ReplyParameters

from poweron.core.domain.models import MessageKind
from poweron.core.ports import DeliveryTargetGone

from . import texts
from .keyboards import menu_keyboard
from .render import render_planned_work, render_reminder, render_subqueues_changed, render_update

SEND_INTERVAL = 0.04
CHAT_GONE_MARKERS = ("chat not found", "user not found")


def _render(kind: str, payload: Mapping[str, Any]) -> str:
    match kind:
        case MessageKind.SCHEDULE_UPDATED:
            return render_update(payload, datetime.now(UTC))
        case MessageKind.REMINDER_OFF:
            return render_reminder(payload, power_on=False)
        case MessageKind.REMINDER_ON:
            return render_reminder(payload, power_on=True)
        case MessageKind.SUBQUEUES_CHANGED:
            return render_subqueues_changed(payload)
        case MessageKind.PLANNED_WORK:
            return render_planned_work(payload)
        case MessageKind.MENU_UPDATED:
            return texts.MENU_UPDATED
        case MessageKind.FEEDBACK_REPLY:
            return texts.FEEDBACK_REPLY.format(text=escape(payload["text"]))
        case _:
            raise ValueError(f"unknown message kind {kind!r}")


def message_ref(chat_id: int, message_id: int) -> str:
    return f"telegram:{chat_id}:{message_id}"


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._slot_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> str:
        text = _render(kind, payload)
        reply_to = payload.get("reply_to")
        await self._wait_for_slot()
        try:
            sent = await self._bot.send_message(
                int(address),
                text,
                # A reply keyboard only changes when a message brings one, so every push refreshes it.
                reply_markup=menu_keyboard(),
                # News about the menu alone is not worth a buzz.
                disable_notification=True if kind == MessageKind.MENU_UPDATED else None,
                # Still sent when the user has deleted the message it answers.
                reply_parameters=None
                if reply_to is None
                else ReplyParameters(message_id=reply_to, allow_sending_without_reply=True),
            )
        except TelegramForbiddenError as error:
            raise DeliveryTargetGone(address) from error
        except TelegramBadRequest as error:
            if any(marker in error.message.lower() for marker in CHAT_GONE_MARKERS):
                raise DeliveryTargetGone(address) from error
            raise
        return message_ref(int(address), sent.message_id)

    async def _wait_for_slot(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._slot_lock:
            await asyncio.sleep(max(0.0, self._next_slot - loop.time()))
            self._next_slot = loop.time() + SEND_INTERVAL

import asyncio
from collections.abc import Mapping
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import LinkPreviewOptions

from poweron.core.domain.models import MessageKind
from poweron.core.ports import DeliveryTargetGone

from .render import render_update

SEND_INTERVAL = 0.04
CHAT_GONE_MARKERS = ("chat not found", "user not found")


class TelegramNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot
        self._slot_lock = asyncio.Lock()
        self._next_slot = 0.0

    async def send(self, address: str, kind: str, payload: Mapping[str, Any]) -> None:
        if kind != MessageKind.SCHEDULE_UPDATED:
            raise ValueError(f"unknown message kind {kind!r}")
        text = render_update(payload)
        await self._wait_for_slot()
        try:
            await self._bot.send_message(
                int(address),
                text,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
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

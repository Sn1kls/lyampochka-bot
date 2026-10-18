from html import escape

from aiogram import Bot

from poweron.core.domain.models import AlertKind

from . import texts

MAX_DETAILS = 500
ALERT_TEXTS = {
    AlertKind.API_SCHEMA: texts.ALERT_API_SCHEMA,
    AlertKind.API_DOWN: texts.ALERT_API_DOWN,
    AlertKind.NEW_USER: texts.ALERT_NEW_USER,
    AlertKind.BACKUP_FAILED: texts.ALERT_BACKUP_FAILED,
}


class TelegramAdminAlerter:
    def __init__(self, bot: Bot, chat_id: int) -> None:
        self._bot = bot
        self._chat_id = chat_id

    async def alert(self, kind: AlertKind, details: str) -> None:
        text = ALERT_TEXTS[kind].format(details=escape(details[:MAX_DETAILS]))
        await self._bot.send_message(self._chat_id, text)

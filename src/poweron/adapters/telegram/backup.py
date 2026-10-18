import asyncio

from aiogram import Bot
from aiogram.types import BufferedInputFile

from poweron.adapters.backup_crypto import encrypt

from . import texts


class TelegramBackupSink:
    def __init__(self, bot: Bot, chat_id: int, password: str) -> None:
        self._bot = bot
        self._chat_id = chat_id
        self._password = password

    async def store(self, name: str, content: bytes) -> None:
        # scrypt and encryption are CPU work; off the event loop the bot keeps answering meanwhile.
        encrypted = await asyncio.to_thread(encrypt, content, self._password)
        await self._bot.send_document(
            self._chat_id,
            BufferedInputFile(encrypted, filename=f"{name}.enc"),
            caption=texts.BACKUP_CAPTION.format(name=name),
        )

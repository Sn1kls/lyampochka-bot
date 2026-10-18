from aiogram.types import BufferedInputFile

from poweron.adapters.backup_crypto import decrypt
from poweron.adapters.telegram import texts
from poweron.adapters.telegram.backup import TelegramBackupSink


class FakeBot:
    def __init__(self) -> None:
        self.documents: list[tuple[int, BufferedInputFile, str]] = []

    async def send_document(self, chat_id: int, document: BufferedInputFile, caption: str) -> None:
        self.documents.append((chat_id, document, caption))


async def test_the_sink_sends_an_encrypted_document_to_the_admin_chat() -> None:
    bot = FakeBot()
    sink = TelegramBackupSink(bot, 42, "secret")  # type: ignore[arg-type]

    await sink.store("poweron-2026-10-19.sqlite3", b"database")

    [(chat_id, document, caption)] = bot.documents
    assert chat_id == 42
    assert document.filename == "poweron-2026-10-19.sqlite3.enc"
    assert decrypt(document.data, "secret") == b"database"
    assert caption == texts.BACKUP_CAPTION.format(name="poweron-2026-10-19.sqlite3")

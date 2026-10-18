import pytest

from poweron.adapters.telegram import texts
from poweron.adapters.telegram.alerts import MAX_DETAILS, TelegramAdminAlerter
from poweron.core.domain.models import AlertKind


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        self.sent.append((chat_id, text))


@pytest.mark.parametrize(
    ("kind", "template"),
    [
        (AlertKind.API_SCHEMA, texts.ALERT_API_SCHEMA),
        (AlertKind.API_DOWN, texts.ALERT_API_DOWN),
        (AlertKind.NEW_USER, texts.ALERT_NEW_USER),
        (AlertKind.BACKUP_FAILED, texts.ALERT_BACKUP_FAILED),
    ],
)
async def test_alert_goes_to_the_admin_chat_with_escaped_details(
    kind: AlertKind, template: str
) -> None:
    bot = FakeBot()

    await TelegramAdminAlerter(bot, 42).alert(kind, "<html> & more")  # type: ignore[arg-type]

    assert bot.sent == [(42, template.format(details="&lt;html&gt; &amp; more"))]


async def test_alert_details_are_truncated() -> None:
    bot = FakeBot()

    await TelegramAdminAlerter(bot, 42).alert(AlertKind.API_DOWN, "x" * 2000)  # type: ignore[arg-type]

    assert bot.sent[0][1].count("x") == MAX_DETAILS

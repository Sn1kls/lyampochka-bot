from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BotCommand

from poweron.adapters.telegram import texts
from poweron.adapters.telegram.bot import build_dispatcher, create_bot, publish_profile


def test_dispatcher_carries_services_and_bot_defaults_to_html() -> None:
    services: dict[str, object] = {"subscriptions": 1, "catalogs": 2, "schedules": 3, "feedback": 4}
    dispatcher = build_dispatcher(**services)  # type: ignore[arg-type]

    assert dispatcher.workflow_data == {
        **services,
        "status": None,
        "admin_chat_id": None,
        "outages": None,
    }
    bot = create_bot("123:abc")
    assert bot.default.parse_mode == "HTML"
    assert bot.default.link_preview_is_disabled is True


async def test_command_menu_and_descriptions_are_published() -> None:
    class RecordingBot:
        commands: list[BotCommand] = []
        short_description = ""
        description = ""

        async def set_my_commands(self, commands: list[BotCommand]) -> None:
            self.commands = commands

        async def set_my_short_description(self, short_description: str) -> None:
            self.short_description = short_description

        async def set_my_description(self, description: str) -> None:
            self.description = description

    bot = RecordingBot()
    await publish_profile(bot)  # type: ignore[arg-type]

    assert [(item.command, item.description) for item in bot.commands] == list(texts.COMMANDS)
    assert bot.short_description == texts.ABOUT
    assert bot.description == texts.DESCRIPTION


def test_descriptions_fit_telegram_limits() -> None:
    def utf16_length(text: str) -> int:
        return len(text.encode("utf-16-le")) // 2

    assert utf16_length(texts.ABOUT) <= 120
    assert utf16_length(texts.DESCRIPTION) <= 512


def test_help_explains_the_buttons_not_the_commands() -> None:
    for button in (texts.MENU_SCHEDULE, texts.MENU_NEXT, texts.MENU_LIST, texts.MENU_SETTINGS):
        assert button in texts.HELP
    assert "/forget" in texts.HELP
    assert "/add" not in texts.HELP


async def test_one_failing_profile_call_neither_stops_the_bot_nor_skips_the_rest() -> None:
    class PartlyFailingBot:
        published: list[str] = []

        async def set_my_commands(self, commands: list[BotCommand]) -> None:
            raise TelegramNetworkError(method=None, message="timeout")  # type: ignore[arg-type]

        async def set_my_short_description(self, short_description: str) -> None:
            self.published.append(short_description)

        async def set_my_description(self, description: str) -> None:
            self.published.append(description)

    bot = PartlyFailingBot()
    await publish_profile(bot)  # type: ignore[arg-type]

    assert bot.published == [texts.ABOUT, texts.DESCRIPTION]

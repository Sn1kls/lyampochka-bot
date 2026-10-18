from aiogram.exceptions import TelegramNetworkError
from aiogram.types import BotCommand

from poweron.adapters.telegram import texts
from poweron.adapters.telegram.bot import build_dispatcher, create_bot, publish_commands


def test_dispatcher_carries_services_and_bot_defaults_to_html() -> None:
    services: dict[str, object] = {"subscriptions": 1, "catalog": 2, "schedules": 3}
    dispatcher = build_dispatcher(**services)  # type: ignore[arg-type]

    assert dispatcher.workflow_data == {**services, "status": None, "admin_chat_id": None}
    bot = create_bot("123:abc")
    assert bot.default.parse_mode == "HTML"
    assert bot.default.link_preview_is_disabled is True


async def test_command_menu_is_published() -> None:
    class RecordingBot:
        commands: list[BotCommand] = []

        async def set_my_commands(self, commands: list[BotCommand]) -> None:
            self.commands = commands

    bot = RecordingBot()
    await publish_commands(bot)  # type: ignore[arg-type]

    assert [(item.command, item.description) for item in bot.commands] == list(texts.COMMANDS)


def test_help_explains_the_buttons_not_the_commands() -> None:
    for button in (texts.MENU_SCHEDULE, texts.MENU_NEXT, texts.MENU_LIST, texts.MENU_SETTINGS):
        assert button in texts.HELP
    assert "/forget" in texts.HELP
    assert "/add" not in texts.HELP


async def test_a_failing_command_menu_does_not_stop_the_bot() -> None:
    class FailingBot:
        async def set_my_commands(self, commands: list[BotCommand]) -> None:
            raise TelegramNetworkError(method=None, message="timeout")  # type: ignore[arg-type]

    await publish_commands(FailingBot())  # type: ignore[arg-type]

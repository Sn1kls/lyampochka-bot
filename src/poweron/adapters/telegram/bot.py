import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from poweron.core.services.catalog import Catalog
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions

from . import texts
from .handlers import router

logger = logging.getLogger(__name__)


def create_bot(token: str) -> Bot:
    return Bot(
        token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def build_dispatcher(
    subscriptions: Subscriptions, catalog: Catalog, schedules: Schedules
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        subscriptions=subscriptions,
        catalog=catalog,
        schedules=schedules,
    )
    dispatcher.include_router(router)
    dispatcher.startup.register(publish_commands)
    return dispatcher


async def publish_commands(bot: Bot) -> None:
    """The command menu Telegram shows when the user types "/"; cosmetic, so never fatal."""
    try:
        await bot.set_my_commands(
            [BotCommand(command=command, description=text) for command, text in texts.COMMANDS]
        )
    except TelegramAPIError as error:
        logger.warning("could not publish the command menu: %r", error)

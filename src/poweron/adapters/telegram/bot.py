import logging
from collections.abc import Mapping

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from poweron.core.services.catalog import Catalog
from poweron.core.services.feedback import Feedback
from poweron.core.services.schedules import Schedules
from poweron.core.services.status import Status
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
    subscriptions: Subscriptions,
    catalogs: Mapping[str, Catalog],
    schedules: Schedules,
    feedback: Feedback,
    *,
    status: Status | None = None,
    admin_chat_id: int | None = None,
) -> Dispatcher:
    dispatcher = Dispatcher(
        storage=MemoryStorage(),
        subscriptions=subscriptions,
        catalogs=catalogs,
        schedules=schedules,
        status=status,
        admin_chat_id=admin_chat_id,
        feedback=feedback,
    )
    dispatcher.include_router(router)
    dispatcher.startup.register(publish_profile)
    return dispatcher


async def publish_profile(bot: Bot) -> None:
    """The "/" command menu and the profile texts; cosmetic, so never fatal, each on its own."""
    commands = [BotCommand(command=command, description=text) for command, text in texts.COMMANDS]
    for request in (
        bot.set_my_commands(commands),
        bot.set_my_short_description(short_description=texts.ABOUT),
        bot.set_my_description(description=texts.DESCRIPTION),
    ):
        try:
            await request
        except TelegramAPIError as error:
            logger.warning("could not publish the bot profile: %r", error)

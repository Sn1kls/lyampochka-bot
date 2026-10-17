from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from poweron.core.services.catalog import Catalog
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions

from .handlers import router


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
    return dispatcher

import asyncio
import logging
import sys

from poweron.adapters.db.repository import SqlRepository, create_engine, run_migrations
from poweron.adapters.telegram.bot import build_dispatcher, create_bot
from poweron.adapters.telegram.notifier import TelegramNotifier
from poweron.adapters.toe_api.client import ToeClient
from poweron.config import Settings
from poweron.core.services.catalog import Catalog
from poweron.core.services.groups import GroupResolver
from poweron.core.services.notifications import Notifications
from poweron.core.services.polling import Polling
from poweron.core.services.reminders import Reminders
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import Subscriptions
from poweron.worker.runner import run_worker

ROLES = ("bot", "worker", "all")


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else "all"
    if role not in ROLES:
        sys.exit(f"usage: python -m poweron [{'|'.join(ROLES)}]")
    settings = Settings()  # values come from the environment
    logging.basicConfig(
        level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    # httpx logs full request URLs at INFO, and those carry the user's street and building.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    # Alembic runs its own event loop, so migrate before ours starts.
    run_migrations(settings.database_url)
    asyncio.run(run(role, settings))


async def run(role: str, settings: Settings) -> None:
    engine = create_engine(settings.database_url)
    repository = SqlRepository(engine)
    toe_client = ToeClient(settings.api_base, contact=settings.contact)
    bot = create_bot(settings.bot_token.get_secret_value())
    try:
        async with asyncio.TaskGroup() as group:
            if role in ("bot", "all"):
                dispatcher = build_dispatcher(
                    Subscriptions(repository),
                    Catalog(repository, toe_client),
                    Schedules(repository),
                )
                group.create_task(dispatcher.start_polling(bot, handle_signals=False))
            if role in ("worker", "all"):
                notifications = Notifications(repository, {"telegram": TelegramNotifier(bot)})
                group.create_task(
                    run_worker(
                        Polling(repository, toe_client),
                        notifications,
                        Reminders(repository),
                        GroupResolver(repository, toe_client),
                        settings.poll_interval_sec,
                    )
                )
    finally:
        await toe_client.aclose()
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    main()

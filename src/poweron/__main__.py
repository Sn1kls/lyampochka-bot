import asyncio
import logging
import signal
import sys
from datetime import timedelta
from importlib.metadata import version

from aiogram import Bot, Dispatcher

from poweron.adapters.db.repository import SqlRepository, create_engine, run_migrations
from poweron.adapters.healthcheck import HealthcheckPinger
from poweron.adapters.telegram.alerts import TelegramAdminAlerter
from poweron.adapters.telegram.backup import TelegramBackupSink
from poweron.adapters.telegram.bot import build_dispatcher, create_bot
from poweron.adapters.telegram.notifier import TelegramNotifier
from poweron.adapters.toe_api.client import ToeClient
from poweron.config import Settings
from poweron.core.services.alerts import Alerts
from poweron.core.services.backups import Backups
from poweron.core.services.catalog import Catalog
from poweron.core.services.groups import SubqueueChecker
from poweron.core.services.notifications import Notifications
from poweron.core.services.planned_works import PlannedWorks
from poweron.core.services.polling import Polling
from poweron.core.services.reminders import Reminders
from poweron.core.services.schedules import Schedules
from poweron.core.services.status import Status
from poweron.core.services.subscriptions import Subscriptions
from poweron.worker.runner import run_worker

logger = logging.getLogger(__name__)

ROLES = ("bot", "worker", "all")
STOP_RETRY_DELAY = 0.1


def main() -> None:
    role = sys.argv[1] if len(sys.argv) > 1 else "all"
    if role not in ROLES:
        sys.exit(f"usage: python -m poweron [{'|'.join(ROLES)}]")
    settings = Settings()  # values come from the environment
    logging.basicConfig(
        level=settings.log_level,
        format="ts=%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)s",
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
    alerts = (
        None
        if settings.admin_chat_id is None
        else Alerts(TelegramAdminAlerter(bot, settings.admin_chat_id))
    )
    heartbeat = (
        None
        if settings.healthcheck_url is None
        else HealthcheckPinger(settings.healthcheck_url.get_secret_value())
    )
    stop = asyncio.Event()
    _stop_on_signals(stop)
    try:
        async with asyncio.TaskGroup() as group:
            if role in ("bot", "all"):
                dispatcher = build_dispatcher(
                    Subscriptions(repository, alerts),
                    Catalog(repository, toe_client),
                    Schedules(repository),
                    status=Status(
                        repository,
                        f"{version('poweron')} ({settings.git_sha})",
                        timedelta(seconds=settings.poll_interval_sec),
                    ),
                    admin_chat_id=settings.admin_chat_id,
                )
                polling_task = group.create_task(
                    dispatcher.start_polling(bot, handle_signals=False)
                )
                group.create_task(_stop_polling_on(stop, dispatcher, polling_task))
            if role in ("worker", "all"):
                notifications = Notifications(repository, {"telegram": TelegramNotifier(bot)})
                group.create_task(
                    run_worker(
                        Polling(repository, toe_client, alerts),
                        notifications,
                        Reminders(repository, Schedules(repository)),
                        SubqueueChecker(repository, toe_client, alerts),
                        PlannedWorks(repository, toe_client, alerts),
                        settings.poll_interval_sec,
                        stop,
                        heartbeat,
                        _backups(settings, repository, bot, alerts),
                    )
                )
    finally:
        await toe_client.aclose()
        await bot.session.close()
        await engine.dispose()


def _backups(
    settings: Settings, repository: SqlRepository, bot: Bot, alerts: Alerts | None
) -> Backups | None:
    if settings.admin_chat_id is None or settings.backup_password is None:
        logger.info("daily backups are off: set ADMIN_CHAT_ID and BACKUP_PASSWORD to turn them on")
        return None
    if not settings.database_url.startswith("sqlite"):
        logger.info("daily backups are off: they are implemented for SQLite only")
        return None
    sink = TelegramBackupSink(
        bot, settings.admin_chat_id, settings.backup_password.get_secret_value()
    )
    return Backups(repository, sink, alerts)


def _stop_on_signals(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signal_number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signal_number, stop.set)


async def _stop_polling_on(
    stop: asyncio.Event, dispatcher: Dispatcher, polling_task: asyncio.Task[None]
) -> None:
    await stop.wait()
    logger.info("stop requested")
    # A stop that arrives before polling has started raises; keep trying until it takes.
    while not polling_task.done():
        try:
            await dispatcher.stop_polling()
            return
        except RuntimeError:
            await asyncio.sleep(STOP_RETRY_DELAY)


if __name__ == "__main__":
    main()

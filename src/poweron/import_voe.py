"""Replace the Volyn address → queue catalogue with a `scripts/export_volyn_queues.py` file.

    python -m poweron.import_voe [--force] < export.jsonl.gz

A separate entry point from `python -m poweron`: it must not import aiogram (~100 MB) while it
holds the whole catalogue in memory on a small VM.
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from poweron.adapters.db.repository import create_engine, run_migrations
from poweron.adapters.db.voe_catalog import (
    CatalogImportRefused,
    CatalogRow,
    ImportSummary,
    VoeCatalog,
    parse_export,
)
from poweron.config import Settings
from poweron.observability import init_sentry


def main() -> None:
    settings = Settings()  # values come from the environment
    init_sentry(settings)
    run_migrations(settings.database_url)
    try:
        rows, skipped = parse_export(sys.stdin.buffer.read())
        summary = asyncio.run(_replace(settings.database_url, rows, "--force" in sys.argv))
    except CatalogImportRefused as error:
        # Logged as an error, so Sentry reports it: a refused import needs a look.
        logging.getLogger(__name__).error("import refused: %s", error)
        sys.exit(f"import refused: {error}")
    del rows  # free the catalogue before aiogram is loaded for the admin message
    report = (
        f"{summary.buildings} buildings (was {summary.previous_buildings}), "
        f"{summary.changed} changed, {skipped} rows skipped"
    )
    print(report)
    if summary.changed and settings.admin_chat_id is not None:
        asyncio.run(_tell_admin(settings, settings.admin_chat_id, report))


async def _replace(database_url: str, rows: list[CatalogRow], force: bool) -> ImportSummary:
    engine = create_engine(database_url)
    try:
        return await VoeCatalog(engine).replace(rows, datetime.now(UTC), force)
    finally:
        await engine.dispose()


async def _tell_admin(settings: Settings, admin_chat_id: int, report: str) -> None:
    # Imported here, after the catalogue is freed: see the module docstring.
    from poweron.adapters.telegram.alerts import TelegramAdminAlerter
    from poweron.adapters.telegram.bot import create_bot
    from poweron.core.domain.models import AlertKind
    from poweron.core.services.alerts import Alerts

    bot = create_bot(settings.bot_token.get_secret_value())
    try:
        alerts = Alerts(TelegramAdminAlerter(bot, admin_chat_id))
        await alerts.send(AlertKind.VOE_CATALOG_IMPORTED, report)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    main()

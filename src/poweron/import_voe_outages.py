"""Replace the Volyn outages snapshot with a `scripts/export_volyn_outages.py` answer.

    python -m poweron.import_voe_outages < outages.json

Runs every 15 minutes inside the running bot container (`docker compose exec`), whose memory
limit it shares, so it stays light: no aiogram, no migrations (the bot ran them on start).
"""

import asyncio
import logging
import sys
from datetime import UTC, datetime

from poweron.adapters.db.repository import create_engine
from poweron.adapters.db.voe_outages import (
    MAX_SNAPSHOT_BYTES,
    OutageRow,
    OutagesImportRefused,
    VoeOutages,
    parse_snapshot,
)
from poweron.config import Settings
from poweron.observability import init_sentry


def main() -> None:
    settings = Settings()  # values come from the environment
    init_sentry(settings)
    try:
        rows, skipped = parse_snapshot(sys.stdin.buffer.read(MAX_SNAPSHOT_BYTES + 1))
    except OutagesImportRefused as error:
        # Logged as an error, so Sentry reports it: the export format or the site changed.
        logging.getLogger(__name__).error("import refused: %s", error)
        sys.exit(f"import refused: {error}")
    asyncio.run(_replace(settings.database_url, rows))
    print(f"{len(rows)} outages, {skipped} rows skipped")


async def _replace(database_url: str, rows: list[OutageRow]) -> None:
    engine = create_engine(database_url)
    try:
        await VoeOutages(engine).replace(rows, datetime.now(UTC))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    main()

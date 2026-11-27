"""Remind users who have no address to add one.

Each user gets it once ever, so a rerun is harmless; users who joined less than a day ago wait.
Run where the bot runs: `make nudge-no-address`. The worker delivers it on its next dispatch.
Run only after the release with it is deployed: an older worker cannot render it, gives up
after its retries, and the once-ever key keeps a rerun from queueing it again.
"""

import asyncio
from datetime import UTC, datetime

from poweron.adapters.db.repository import SqlRepository, create_engine
from poweron.config import Settings
from poweron.core.services.announcements import Announcements


async def main() -> None:
    settings = Settings(bot_token="unused")  # type: ignore[arg-type]
    engine = create_engine(settings.database_url)
    queued = await Announcements(SqlRepository(engine)).nudge_without_address(datetime.now(UTC))
    await engine.dispose()
    print(f"{queued} reminder(s) queued; the worker sends them")


if __name__ == "__main__":
    asyncio.run(main())

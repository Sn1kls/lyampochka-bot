"""Send every user the current reply keyboard after it changes.

Each user gets it once per VERSION, so a rerun is harmless; bump VERSION with each menu change.
Run where the bot runs: `make announce-menu VERSION=2`. The worker delivers it on its next dispatch.
"""

import asyncio
import sys

from poweron.adapters.db.repository import SqlRepository, create_engine
from poweron.config import Settings
from poweron.core.services.announcements import Announcements


async def main(version: int) -> None:
    settings = Settings(bot_token="unused")  # type: ignore[arg-type]
    engine = create_engine(settings.database_url)
    queued = await Announcements(SqlRepository(engine)).menu_updated(version)
    await engine.dispose()
    print(f"menu {version}: {queued} message(s) queued; the worker sends them")
    if not queued:
        print("nothing new: everyone already had this version; bump VERSION for a new menu")


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        sys.exit("usage: python scripts/announce_menu.py VERSION  (a whole number)")
    asyncio.run(main(int(sys.argv[1])))

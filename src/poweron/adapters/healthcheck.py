import logging

import httpx

logger = logging.getLogger(__name__)

TIMEOUT = 10.0


class HealthcheckPinger:
    """Pings a healthchecks.io-style URL; the monitor alerts the owner when pings stop."""

    def __init__(self, url: str) -> None:
        self._url = url

    async def beat(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                (await client.get(self._url)).raise_for_status()
        except Exception as error:
            # The URL is a secret: anyone with it can fake a heartbeat, so it is not logged.
            logger.warning("heartbeat ping failed: %s", type(error).__name__)

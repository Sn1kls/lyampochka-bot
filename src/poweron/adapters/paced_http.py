import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from poweron.core.ports import ApiSchemaError, SourceUnavailable

ATTEMPTS = 3
RETRY_STATUSES = {429, 500, 502, 503, 504}
MIN_REQUEST_INTERVAL = 1.0
MAX_RETRY_AFTER = 60.0
NOT_JSON = "not JSON"


class PacedHttp:
    """GETs at most one per second, retried on network errors, 429/5xx and non-JSON stubs."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        monotonic: Callable[[], float],
        sleep: Callable[[float], Awaitable[None]],
    ) -> None:
        self._http = http
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_request_at = float("-inf")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(
        self, path: str, params: dict[str, Any], headers: dict[str, str], *, json: bool = False
    ) -> httpx.Response:
        async with self._lock:
            for attempt in range(1, ATTEMPTS + 1):
                wait = self._last_request_at + MIN_REQUEST_INTERVAL - self._monotonic()
                if wait > 0:
                    await self._sleep(wait)
                try:
                    response = await self._http.get(path, params=params, headers=headers)
                except httpx.RequestError as error:
                    failure = f"{type(error).__name__}: {error}"
                    delay = _backoff(attempt)
                else:
                    if response.status_code == 200:
                        try:
                            if json:
                                response.json()
                            return response
                        except ValueError:  # a server coming back up can answer 200 with a stub
                            failure = NOT_JSON
                            delay = _backoff(attempt)
                    elif response.status_code not in RETRY_STATUSES:
                        raise SourceUnavailable(f"{path}: HTTP {response.status_code}")
                    else:
                        failure = f"HTTP {response.status_code}"
                        delay = _retry_after(response) or _backoff(attempt)
                finally:
                    self._last_request_at = self._monotonic()
                if attempt < ATTEMPTS:
                    await self._sleep(delay)
            if failure == NOT_JSON:
                raise ApiSchemaError(f"{path}: {NOT_JSON} after {ATTEMPTS} attempts")
            raise SourceUnavailable(f"{path}: {failure} after {ATTEMPTS} attempts")


def _backoff(attempt: int) -> float:
    return float(2**attempt) + random.uniform(0, 1)


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After", "")
    return min(float(value), MAX_RETRY_AFTER) if value.isdigit() else None

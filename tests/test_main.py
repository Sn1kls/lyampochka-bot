import asyncio
from dataclasses import dataclass

from poweron.__main__ import _stop_polling_on


@dataclass
class FakeDispatcher:
    failures_left: int
    stopped: bool = False

    async def stop_polling(self) -> None:
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("Polling is not started")
        self.stopped = True


async def test_stop_is_retried_until_polling_has_started() -> None:
    stop = asyncio.Event()
    stop.set()
    dispatcher = FakeDispatcher(failures_left=2)
    polling = asyncio.create_task(asyncio.sleep(3600))

    await asyncio.wait_for(_stop_polling_on(stop, dispatcher, polling), timeout=5)  # type: ignore[arg-type]

    assert dispatcher.stopped
    polling.cancel()


async def test_retrying_ends_when_polling_is_gone() -> None:
    stop = asyncio.Event()
    stop.set()
    dispatcher = FakeDispatcher(failures_left=10**6)
    polling = asyncio.create_task(asyncio.sleep(0))

    await asyncio.wait_for(_stop_polling_on(stop, dispatcher, polling), timeout=5)  # type: ignore[arg-type]

    assert not dispatcher.stopped

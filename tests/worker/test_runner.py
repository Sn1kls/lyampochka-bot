import asyncio

import pytest

from poweron.worker import runner
from poweron.worker.runner import repeat


@pytest.fixture(autouse=True)
def short_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "MIN_DELAY", 0.01)


async def test_a_failing_job_does_not_stop_the_loop() -> None:
    stop = asyncio.Event()
    calls = []

    async def job() -> None:
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("first run fails")
        stop.set()

    await asyncio.wait_for(repeat(job, stop, 0.01), timeout=5)

    assert calls == [0, 1]


async def test_a_running_job_finishes_before_the_loop_exits() -> None:
    stop = asyncio.Event()
    started = asyncio.Event()
    persisted = []

    async def job() -> None:
        started.set()
        await asyncio.sleep(0.05)
        persisted.append("done")

    loop_task = asyncio.create_task(repeat(job, stop, 3600))
    await started.wait()
    stop.set()
    await asyncio.wait_for(loop_task, timeout=5)

    assert persisted == ["done"]


async def test_stop_interrupts_the_wait_between_runs() -> None:
    stop = asyncio.Event()
    calls = []

    async def job() -> None:
        calls.append(1)

    loop_task = asyncio.create_task(repeat(job, stop, 3600))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(loop_task, timeout=5)

    assert calls == [1]


class FakePolling:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    async def poll(self, *_: object) -> None:
        if self.error is not None:
            raise self.error


class FakeHeartbeat:
    def __init__(self) -> None:
        self.beats = 0

    async def beat(self) -> None:
        self.beats += 1


async def test_the_heartbeat_follows_a_finished_poll() -> None:
    heartbeat = FakeHeartbeat()

    await runner.poll_then_beat(FakePolling(), heartbeat, asyncio.Event())  # type: ignore[arg-type]

    assert heartbeat.beats == 1


async def test_a_crashed_poll_skips_the_heartbeat() -> None:
    heartbeat = FakeHeartbeat()

    with pytest.raises(RuntimeError):
        await runner.poll_then_beat(FakePolling(RuntimeError("boom")), heartbeat, asyncio.Event())  # type: ignore[arg-type]

    assert heartbeat.beats == 0

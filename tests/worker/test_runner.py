import asyncio

import pytest

from poweron.worker.runner import repeat


async def test_a_failing_job_does_not_stop_the_loop() -> None:
    calls = []

    async def job() -> None:
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("first run fails")

    async def sleep(_seconds: float) -> None:
        if len(calls) == 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await repeat(job, 1.0, sleep=sleep)
    assert calls == [0, 1]

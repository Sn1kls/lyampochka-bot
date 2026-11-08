import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

from poweron.config import Settings
from poweron.observability import sentry_options

TOKEN = "123456:secret-bot-token"
ADDRESS = "Ківерці, Незалежності, 19"


class CapturingTransport(Transport):
    def __init__(self, options: dict[str, Any] | None = None) -> None:
        super().__init__(options)
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        self.events += [item.payload.json for item in envelope.items if item.type == "event"]


def settings(**values: Any) -> Settings:
    return Settings(_env_file=None, bot_token=TOKEN, git_sha="abc1234", **values)  # type: ignore[call-arg]


@pytest.fixture
def transport() -> Iterator[CapturingTransport]:
    options = sentry_options(settings(sentry_dsn="https://key@o1.ingest.sentry.io/2"))
    assert options is not None
    capturing = CapturingTransport()
    sentry_sdk.init(**options, transport=capturing)
    yield capturing
    sentry_sdk.init()  # back to a disabled client


def test_sentry_is_off_without_a_dsn() -> None:
    assert sentry_options(settings()) is None


def failing_job() -> None:
    address = ADDRESS  # a local variable, as in the real handlers
    raise RuntimeError(f"failed for {len(address)} chars")


@respx.mock
async def test_an_error_reaches_sentry_without_addresses_or_secrets(
    transport: CapturingTransport,
) -> None:
    respx.get(url__startswith="https://api.example.test/").respond(200)
    async with httpx.AsyncClient() as client:
        await client.get("https://api.example.test/a_gpv_g", params={"time": ADDRESS})
    logging.getLogger("poweron.worker").warning("telegram said no to bot%s", TOKEN)

    try:
        failing_job()
    except RuntimeError:
        logging.getLogger("poweron.worker").exception("worker job failed")
    sentry_sdk.flush()

    [event] = transport.events
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    for frame in frames:  # source lines around a frame are code, not data
        for key in ("pre_context", "context_line", "post_context"):
            frame.pop(key, None)
    sent = json.dumps(event, ensure_ascii=False)
    breadcrumbs = event["breadcrumbs"]["values"]
    assert [crumb["category"] for crumb in breadcrumbs] == ["poweron.worker"]
    assert event["release"].startswith("poweron@") and event["release"].endswith("+abc1234")
    assert "RuntimeError" in sent
    assert ADDRESS not in sent  # no local variables, no httpx breadcrumb with the URL
    assert "api.example.test" not in sent
    assert TOKEN not in sent
    assert all("vars" not in frame for frame in frames)

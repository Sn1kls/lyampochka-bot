import httpx
import respx

from poweron.adapters.healthcheck import HealthcheckPinger

URL = "https://hc-ping.com/test-uuid"


@respx.mock
async def test_a_beat_pings_the_url() -> None:
    route = respx.get(URL).respond(200)

    await HealthcheckPinger(URL).beat()

    assert route.called


@respx.mock
async def test_a_failed_ping_never_raises() -> None:
    respx.get(URL).mock(side_effect=httpx.ConnectError("down"))

    await HealthcheckPinger(URL).beat()


async def test_a_broken_url_never_raises() -> None:
    await HealthcheckPinger("https://hc-ping.com:notaport/x").beat()

import struct
import zlib
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime

import httpx
import pytest
import respx

from poweron.adapters.voe_api.client import VoeClient
from poweron.adapters.voe_api.image import decode_schedule
from poweron.core.domain.models import KYIV, Address
from poweron.core.ports import ApiSchemaError, SourceUnavailable
from tests.conftest import FIXTURES, load_fixture

BASE = "https://voe.test"
LIST_URL = f"{BASE}/api/archive_gpv_graphs"
ADDRESS = Address(city_id=0, street_id=0, building_name="")
NOW = datetime(2026, 1, 15, 12, 0, tzinfo=KYIV)
NEWEST_JAN_16 = "/media/2026/01/696a8ced07393_GPV.png"
NEWEST_JAN_15 = "/media/2026/01/69693d81c8c94_GPV.png"
ARCHIVE = load_fixture("voe_archive_2026-01-14_16.json")


def png(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def clock_time(index: int) -> str:
    return f"{index // 2:02d}:{index % 2 * 30:02d}"


def blocks(codes: str) -> list[tuple[str, str]]:
    """OFF stretches as ("HH:MM", "HH:MM") pairs."""
    found = []
    start = None
    for index, code in enumerate(codes + "0"):
        if code == "1" and start is None:
            start = index
        if code == "0" and start is not None:
            found.append((clock_time(start), clock_time(index)))
            start = None
    return found


def tiny_png(colour: tuple[int, int, int], size: int = 4) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        checksum = struct.pack(">I", zlib.crc32(kind + body))
        return struct.pack(">I", len(body)) + kind + body + checksum

    row = b"\x00" + bytes(colour) * size
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * size))
        + chunk(b"IEND", b"")
    )


def test_decodes_2026_01_16() -> None:
    grid = decode_schedule(png("voe_gpv_2026-01-16.png"))

    assert blocks(grid["1.1"]) == [
        ("01:00", "03:00"),
        ("05:00", "07:00"),
        ("08:00", "11:30"),
        ("15:00", "17:00"),
        ("23:00", "24:00"),
    ]
    assert blocks(grid["6.1"]) == [
        ("00:00", "01:00"),
        ("03:00", "05:00"),
        ("07:00", "09:00"),
        ("10:00", "15:00"),
    ]
    assert blocks(grid["3.2"]) == [("00:00", "03:00"), ("05:00", "09:00"), ("11:00", "16:00")]


def test_decodes_2025_12_04() -> None:
    grid = decode_schedule(png("voe_gpv_2025-12-04.png"))

    assert blocks(grid["6.1"]) == [("13:00", "16:30")]
    assert blocks(grid["6.2"]) == [("09:30", "13:00")]
    assert blocks(grid["2.1"]) == []


def test_decodes_an_all_on_day() -> None:
    grid = decode_schedule(png("voe_gpv_2026-02-12_all_on.png"))

    assert len(grid) == 12
    assert set(grid.values()) == {"0" * 48}


@pytest.mark.parametrize(
    "content",
    [b"<html>blocked</html>", png("voe_gpv_2026-01-16.png")[:200], tiny_png((1, 2, 3))],
    ids=["not a png", "truncated", "wrong colour and layout"],
)
def test_a_bad_image_is_a_schema_error(content: bytes) -> None:
    with pytest.raises(ApiSchemaError):
        decode_schedule(content)


class FakeClock:
    def __init__(self) -> None:
        self.monotonic_now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.monotonic_now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.monotonic_now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(clock: FakeClock) -> AsyncIterator[VoeClient]:
    voe_client = VoeClient(BASE, now=lambda: NOW, monotonic=clock.monotonic, sleep=clock.sleep)
    yield voe_client
    await voe_client.aclose()


def mock_archive() -> tuple[respx.Route, respx.Route, respx.Route]:
    return (
        respx.get(LIST_URL).respond(json=ARCHIVE),
        respx.get(f"{BASE}{NEWEST_JAN_16}").respond(content=png("voe_gpv_2026-01-16.png")),
        respx.get(f"{BASE}{NEWEST_JAN_15}").respond(content=png("voe_gpv_2025-12-04.png")),
    )


@respx.mock
async def test_the_newest_revision_of_each_day_wins(client: VoeClient) -> None:
    mock_archive()

    result = await client.fetch_schedules(ADDRESS, "voe:6.1")

    assert [schedule.day for schedule in result] == [date(2026, 1, 15), date(2026, 1, 16)]
    assert [schedule.cherg_gpv for schedule in result] == ["voe:6.1", "voe:6.1"]
    assert result[0].created_at == datetime(2026, 1, 15, 21, 18, 25, tzinfo=UTC)
    assert result[1].created_at == datetime(2026, 1, 16, 21, 9, 33, tzinfo=UTC)
    assert blocks("".join(result[1].slots.values())) == [
        ("00:00", "01:00"),
        ("03:00", "05:00"),
        ("07:00", "09:00"),
        ("10:00", "15:00"),
    ]
    assert list(result[1].slots)[:3] == ["00:00", "00:30", "01:00"]
    assert list(result[1].slots)[-1] == "23:30"


@respx.mock
async def test_a_pass_over_subqueues_costs_one_list_and_one_download_per_image(
    client: VoeClient,
) -> None:
    listing, jan_16, jan_15 = mock_archive()

    for subqueue in ("voe:1.1", "voe:6.1"):
        await client.fetch_schedules(ADDRESS, subqueue)

    assert (listing.call_count, jan_16.call_count, jan_15.call_count) == (1, 1, 1)


@respx.mock
async def test_the_list_is_fetched_again_after_the_cache_expires(
    client: VoeClient, clock: FakeClock
) -> None:
    listing, jan_16, _ = mock_archive()

    await client.fetch_schedules(ADDRESS, "voe:1.1")
    clock.monotonic_now += 61
    await client.fetch_schedules(ADDRESS, "voe:1.1")

    assert (listing.call_count, jan_16.call_count) == (2, 1)


@respx.mock
async def test_the_request_uses_the_sites_date_format(client: VoeClient) -> None:
    listing, _, _ = mock_archive()

    await client.fetch_schedules(ADDRESS, "voe:1.1")

    request = listing.calls.last.request
    assert request.url.params["dateGraph[after]"] == "2026-01-15T00:00:00+02:00Z"
    assert request.url.params["dateGraph[before]"] == "2026-01-16T00:00:00+02:00Z"
    assert request.headers["Accept"] == "application/ld+json"
    assert request.headers["User-Agent"].startswith("poweron-bot/")


@respx.mock
async def test_all_pages_are_read(client: VoeClient) -> None:
    members = ARCHIVE["hydra:member"]
    first = ARCHIVE | {"hydra:member": members[:5]}
    second = ARCHIVE | {"hydra:member": members[5:]}
    listing = respx.get(LIST_URL).mock(
        side_effect=lambda request: httpx.Response(
            200, json=first if request.url.params["page"] == "1" else second
        )
    )
    respx.get(f"{BASE}{NEWEST_JAN_16}").respond(content=png("voe_gpv_2026-01-16.png"))
    respx.get(f"{BASE}{NEWEST_JAN_15}").respond(content=png("voe_gpv_2025-12-04.png"))

    result = await client.fetch_schedules(ADDRESS, "voe:1.1")

    assert [call.request.url.params["page"] for call in listing.calls] == ["1", "2"]
    assert len(result) == 2


@respx.mock
async def test_an_unknown_subqueue_asks_nothing(client: VoeClient) -> None:
    listing, _, _ = mock_archive()

    assert await client.fetch_schedules(ADDRESS, "voe:9.9") == []
    assert listing.call_count == 0


@respx.mock
async def test_requests_are_a_second_apart(client: VoeClient, clock: FakeClock) -> None:
    mock_archive()

    await client.fetch_schedules(ADDRESS, "voe:1.1")

    assert len(clock.sleeps) == 2
    assert all(seconds == pytest.approx(1.0) for seconds in clock.sleeps)


@respx.mock
async def test_server_errors_are_retried_then_unavailable(client: VoeClient) -> None:
    listing = respx.get(LIST_URL).respond(503)

    with pytest.raises(SourceUnavailable):
        await client.fetch_schedules(ADDRESS, "voe:1.1")

    assert listing.call_count == 3


@respx.mock
async def test_client_errors_are_not_retried(client: VoeClient) -> None:
    listing = respx.get(LIST_URL).respond(404)

    with pytest.raises(SourceUnavailable):
        await client.fetch_schedules(ADDRESS, "voe:1.1")

    assert listing.call_count == 1


@respx.mock
async def test_bad_json_is_a_schema_error(client: VoeClient) -> None:
    respx.get(LIST_URL).respond(text="<html>")

    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(ADDRESS, "voe:1.1")


@respx.mock
async def test_an_absolute_image_url_is_rejected(client: VoeClient) -> None:
    member = ARCHIVE["hydra:member"][0] | {"imageUrl": {"contentUrl": "https://evil.test/x.png"}}
    respx.get(LIST_URL).respond(json=ARCHIVE | {"hydra:member": [member], "hydra:totalItems": 1})

    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(ADDRESS, "voe:1.1")

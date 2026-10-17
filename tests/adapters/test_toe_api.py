import base64
import copy
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx

from poweron.adapters.toe_api.client import ToeClient
from poweron.core.domain.models import (
    KYIV,
    Address,
    Building,
    City,
    DaySchedule,
    Street,
)
from poweron.core.ports import ApiSchemaError, SourceUnavailable
from tests.conftest import load_fixture

API = "https://api.test/api"
SADOVA_1 = Address(city_id=1032, street_id=9985, building_name="1")
NOW = datetime(2026, 10, 17, 17, 45, tzinfo=KYIV)


class FakeClock:
    def __init__(self) -> None:
        self.now = NOW
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
async def client(clock: FakeClock) -> AsyncIterator[ToeClient]:
    toe_client = ToeClient(
        API,
        contact="owner@example.com",
        now=lambda: clock.now,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    yield toe_client
    await toe_client.aclose()


def hydra_collection(member: list[Any] | None) -> dict[str, Any]:
    return {"@type": "hydra:Collection", "hydra:member": member}


SCHEDULE = load_fixture("a_gpv_g_4.1_2026-10-17.json")
TIMES = SCHEDULE["hydra:member"][0]["dataJson"]["4.1"]["times"]


def member() -> dict[str, Any]:
    return copy.deepcopy(SCHEDULE["hydra:member"][0])


@respx.mock
async def test_schedule_request_matches_the_site_client(client: ToeClient) -> None:
    route = respx.get(f"{API}/a_gpv_g").respond(json=SCHEDULE)

    result = await client.fetch_schedules(SADOVA_1, "4.1")

    request = route.calls.last.request
    params = request.url.params
    assert params["after"] == "2026-10-16T12:00:00+00:00"
    assert params["before"] == "2026-10-18T17:45:00+00:00"
    assert params["time"] == "103299851"
    assert params["group"] == "4.1"
    assert request.headers["X-debug-key"] == base64.b64encode(b"1032/9985/1").decode()
    assert request.headers["User-Agent"].startswith("poweron-bot/")
    assert "owner@example.com" in request.headers["User-Agent"]
    assert result == [
        DaySchedule(
            cherg_gpv="4.1",
            day=date(2026, 10, 17),
            created_at=datetime(2026, 10, 17, 14, 16, 5, tzinfo=UTC),
            slots=TIMES,
        )
    ]


@respx.mock
async def test_each_poll_gets_a_new_url_to_bypass_the_cdn(
    client: ToeClient, clock: FakeClock
) -> None:
    route = respx.get(f"{API}/a_gpv_g").respond(json=SCHEDULE)
    urls = []
    for _ in range(12 * 24):  # a day of 5-minute polls
        await client.fetch_schedules(SADOVA_1, "4.1")
        urls.append(str(route.calls.last.request.url))
        clock.now += timedelta(minutes=5)

    assert len(set(urls)) == len(urls)


@pytest.mark.parametrize(
    "body",
    [hydra_collection(None), hydra_collection([])],
    ids=["null when nothing published", "[] without key"],
)
@respx.mock
async def test_empty_answers_mean_no_schedules(client: ToeClient, body: dict[str, Any]) -> None:
    respx.get(f"{API}/a_gpv_g").respond(json=body)
    assert await client.fetch_schedules(SADOVA_1, "4.1") == []


@respx.mock
async def test_today_and_tomorrow_are_sorted_by_day(client: ToeClient) -> None:
    tomorrow = member() | {"dateGraph": "2026-10-18T00:00:00Z"}
    respx.get(f"{API}/a_gpv_g").respond(json=hydra_collection([tomorrow, member()]))

    result = await client.fetch_schedules(SADOVA_1, "4.1")

    assert [schedule.day for schedule in result] == [date(2026, 10, 17), date(2026, 10, 18)]


@respx.mock
async def test_only_the_requested_subqueue_is_returned(client: ToeClient) -> None:
    # The site reads dataJson[chergGpv.trim()], "#suffix" included.
    times = member()["dataJson"]["4.1"]
    graph = member() | {"dataJson": {" 4.1#x ": times, "1.2": times}}
    respx.get(f"{API}/a_gpv_g").respond(json=hydra_collection([graph]))

    result = await client.fetch_schedules(SADOVA_1, "4.1#x")

    assert [schedule.cherg_gpv for schedule in result] == ["4.1#x"]


async def test_no_request_for_a_building_without_schedule(client: ToeClient) -> None:
    assert await client.fetch_schedules(SADOVA_1, "Не входить") == []


@respx.mock
async def test_php_empty_data_json_means_no_subqueues(client: ToeClient) -> None:
    respx.get(f"{API}/a_gpv_g").respond(json=hydra_collection([member() | {"dataJson": []}]))
    assert await client.fetch_schedules(SADOVA_1, "4.1") == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>challenge</html>"),
        httpx.Response(200, content=b"\xff\xfe\xfa"),
        httpx.Response(200, json={"@type": "hydra:Collection"}),
        httpx.Response(200, json=hydra_collection([{"dateGraph": "2026-10-17T00:00:00Z"}])),
    ],
    ids=["not json", "not utf-8", "no hydra:member", "member without fields"],
)
@respx.mock
async def test_unexpected_format_raises_schema_error(
    client: ToeClient, response: httpx.Response
) -> None:
    respx.get(f"{API}/a_gpv_g").mock(return_value=response)
    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(SADOVA_1, "4.1")


@respx.mock
async def test_unexpected_slot_key_raises_schema_error(client: ToeClient) -> None:
    bad = member()
    bad["dataJson"]["4.1"]["times"]["24:00"] = "0"
    respx.get(f"{API}/a_gpv_g").respond(json=hydra_collection([bad]))
    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(SADOVA_1, "4.1")


@respx.mock
async def test_429_honours_retry_after(client: ToeClient, clock: FakeClock) -> None:
    route = respx.get(f"{API}/a_gpv_g")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json=SCHEDULE),
    ]

    assert len(await client.fetch_schedules(SADOVA_1, "4.1")) == 1
    assert route.call_count == 2
    assert 7 in clock.sleeps


@respx.mock
async def test_huge_retry_after_is_capped(client: ToeClient, clock: FakeClock) -> None:
    route = respx.get(f"{API}/a_gpv_g")
    route.side_effect = [
        httpx.Response(503, headers={"Retry-After": "86400"}),
        httpx.Response(200, json=SCHEDULE),
    ]
    await client.fetch_schedules(SADOVA_1, "4.1")
    assert max(clock.sleeps) <= 60


@pytest.mark.parametrize(
    "failure",
    [
        httpx.Response(503),
        httpx.ConnectError("boom"),
        httpx.ReadTimeout("slow"),
        httpx.DecodingError("broken gzip"),
    ],
    ids=["503", "connect error", "timeout", "broken body"],
)
@respx.mock
async def test_gives_up_after_three_attempts(client: ToeClient, failure: object) -> None:
    route = respx.get(f"{API}/a_gpv_g")
    route.side_effect = [failure] * 3
    with pytest.raises(SourceUnavailable):
        await client.fetch_schedules(SADOVA_1, "4.1")
    assert route.call_count == 3


@respx.mock
async def test_client_errors_are_not_retried(client: ToeClient) -> None:
    route = respx.get(f"{API}/a_gpv_g").respond(404)
    with pytest.raises(SourceUnavailable):
        await client.fetch_schedules(SADOVA_1, "4.1")
    assert route.call_count == 1


@respx.mock
async def test_requests_are_at_least_one_second_apart(client: ToeClient, clock: FakeClock) -> None:
    respx.get(f"{API}/a_gpv_g").respond(json=SCHEDULE)
    await client.fetch_schedules(SADOVA_1, "4.1")
    await client.fetch_schedules(SADOVA_1, "4.1")
    assert clock.sleeps == [pytest.approx(1.0)]


@pytest.mark.parametrize(
    "wrap", [lambda items: items, lambda items: {"hydra:member": items}], ids=["array", "hydra"]
)
@respx.mock
async def test_cities_in_both_formats(client: ToeClient, wrap: Any) -> None:
    respx.get(f"{API}/pw_cities").respond(json=wrap(load_fixture("pw_cities.json")))
    cities = await client.cities()
    assert len(cities) == 1301
    assert City(id=1032, name="Тернопіль", otg_name="Тернопільська") in cities


@respx.mock
async def test_streets(client: ToeClient) -> None:
    route = respx.get(f"{API}/pw_streets").respond(json=load_fixture("pw_streets_1032.json"))
    streets = await client.streets(1032)
    assert route.calls.last.request.url.params["city.id"] == "1032"
    assert Street(id=9985, name="вул. Садова") in streets


@respx.mock
async def test_buildings_without_schedule_have_no_subqueue(client: ToeClient) -> None:
    respx.get(f"{API}/pw-accounts/building-names").respond(
        json=load_fixture("building_names_1032_9985.json")
    )
    buildings = await client.buildings(1032, 9985)
    assert Building(id=358136, name="1", cherg_gpv="4.1") in buildings
    assert Building(id=350657, name="23", cherg_gpv=None) in buildings

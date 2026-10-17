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
    PlannedWork,
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


async def fail(client: ToeClient) -> None:
    with pytest.raises(SourceUnavailable):
        await client.fetch_schedules(SADOVA_1, "4.1")


@respx.mock
async def test_breaker_opens_after_three_failures_and_backs_off(
    client: ToeClient, clock: FakeClock
) -> None:
    route = respx.get(f"{API}/a_gpv_g").respond(404)
    for _ in range(3):
        await fail(client)
    assert route.call_count == 3

    await fail(client)  # paused: no network call
    clock.monotonic_now += 58
    await fail(client)
    assert route.call_count == 3

    clock.monotonic_now += 2  # the 60 s pause is over, one probe goes out
    await fail(client)
    assert route.call_count == 4

    clock.monotonic_now += 119  # the pause doubled to 120 s
    await fail(client)
    assert route.call_count == 4
    clock.monotonic_now += 1
    await fail(client)
    assert route.call_count == 5


@respx.mock
async def test_breaker_pause_is_capped_at_an_hour(client: ToeClient, clock: FakeClock) -> None:
    route = respx.get(f"{API}/a_gpv_g").respond(404)
    for _ in range(20):
        clock.monotonic_now += 3600
        await fail(client)
    clock.monotonic_now += 3599
    await fail(client)
    assert route.call_count == 20
    clock.monotonic_now += 1
    await fail(client)
    assert route.call_count == 21


@respx.mock
async def test_a_success_closes_the_breaker(client: ToeClient, clock: FakeClock) -> None:
    route = respx.get(f"{API}/a_gpv_g")
    route.side_effect = (
        [httpx.Response(404)] * 3 + [httpx.Response(200, json=SCHEDULE)] + [httpx.Response(404)] * 2
    )
    for _ in range(3):
        await fail(client)
    clock.monotonic_now += 60
    await client.fetch_schedules(SADOVA_1, "4.1")

    await fail(client)
    await fail(client)  # two failures after a success do not open it again
    assert route.call_count == 6


@respx.mock
async def test_schema_errors_do_not_open_the_breaker(client: ToeClient) -> None:
    route = respx.get(f"{API}/a_gpv_g")
    route.side_effect = (
        [httpx.Response(404)] * 2 + [httpx.Response(200, text="<html>")] + [httpx.Response(404)] * 2
    )
    await fail(client)
    await fail(client)
    with pytest.raises(ApiSchemaError):
        await client.fetch_schedules(SADOVA_1, "4.1")
    await fail(client)
    await fail(client)
    assert route.call_count == 5


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


@respx.mock
async def test_building_subqueues_lists_every_group_once_in_order(client: ToeClient) -> None:
    route = respx.get(f"{API}/pw-accounts/building-groups").respond(
        json={
            "filters": {"cityId": 1, "streetId": 7},
            "buildingGroups": [
                {"chergGpv": "2.2"},
                {"chergGpv": " 4.1 "},
                {"chergGpv": "2.2"},
                {"chergGpv": "Не входить"},
                {"chergGpv": ""},
                {"chergGpv": None},
                {},
            ],
        }
    )

    assert await client.building_subqueues(1, 7, "96") == ["2.2", "4.1"]
    params = route.calls.last.request.url.params
    assert (params["cityId"], params["streetId"], params["buildingNames"]) == ("1", "7", "96")


@respx.mock
async def test_building_subqueues_rejects_an_unexpected_shape(client: ToeClient) -> None:
    respx.get(f"{API}/pw-accounts/building-groups").respond(json={"buildingGroups": "none"})

    with pytest.raises(ApiSchemaError):
        await client.building_subqueues(1, 7, "96")


PLANNED = load_fixture("pw_accident_planeds_1032_sample.json")
LIFT_STREET_ID = 44479


@respx.mock
async def test_planned_works_are_parsed_with_kyiv_wall_clock_times(client: ToeClient) -> None:
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=PLANNED), httpx.Response(200, json=[])]
    )

    works = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert works == [
        PlannedWork(
            id=2421,
            street_id=LIFT_STREET_ID,
            starts_at=datetime(2026, 8, 22, 5, 30, tzinfo=UTC),
            ends_at=datetime(2026, 8, 22, 14, 30, tzinfo=UTC),
            reason="Ремонт ПЛ",
            building_names=("1", "3-А", "6", "6-А", "6-Б", "8"),
        )
    ]


@respx.mock
async def test_planned_works_in_winter_time_use_utc_plus_two(client: ToeClient) -> None:
    winter = copy.deepcopy(PLANNED[0])
    winter["dateEvent"] = "2026-12-22T08:30:00+00:00"
    winter["datePlanIn"] = "2026-12-22T17:30:00+00:00"
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[winter]), httpx.Response(200, json=[])]
    )

    (work,) = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert work.starts_at == datetime(2026, 12, 22, 6, 30, tzinfo=UTC)


@respx.mock
async def test_planned_work_without_buildings_or_reason_is_whole_street(client: ToeClient) -> None:
    bare = copy.deepcopy(PLANNED[0]) | {"buildingNames": None, "koment": None}
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[bare]), httpx.Response(200, json=[])]
    )

    (work,) = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert work.building_names == ()
    assert work.reason == ""


@respx.mock
async def test_planned_work_reason_is_one_line(client: ToeClient) -> None:
    messy = copy.deepcopy(PLANNED[2]) | {"street": {"id": LIFT_STREET_ID, "name": "x"}}
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[messy]), httpx.Response(200, json=[])]
    )

    (work,) = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert work.reason == "ТП 400071 тр-р № 1 камера тр-ра № 1 Заміна тр-ра"


@respx.mock
async def test_planned_works_follow_pages_until_an_empty_one(client: ToeClient) -> None:
    second = copy.deepcopy(PLANNED[0]) | {"id": 2500}
    route = respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[
            httpx.Response(200, json=[PLANNED[0]]),
            httpx.Response(200, json=[second]),
            httpx.Response(200, json=[]),
        ]
    )

    works = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert [work.id for work in works] == [2421, 2500]
    assert [call.request.url.params["page"] for call in route.calls] == ["1", "2", "3"]


@respx.mock
async def test_planned_works_stop_after_ten_pages(client: ToeClient) -> None:
    route = respx.get(f"{API}/pw_accident_planeds").respond(json=[PLANNED[0]])

    await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert route.call_count == 10


@respx.mock
async def test_planned_works_request_filters_by_street_and_kyiv_wall_time(
    client: ToeClient,
) -> None:
    route = respx.get(f"{API}/pw_accident_planeds").respond(json=[])

    await client.planned_works(1032, LIFT_STREET_ID, datetime(2026, 10, 17, 18, 40, tzinfo=UTC))

    params = route.calls.last.request.url.params
    assert params["city.id"] == "1032"
    assert params["street.id"] == str(LIFT_STREET_ID)
    assert params["datePlanIn[after]"] == "2026-10-17T21:40:00"
    assert params["page"] == "1"


@respx.mock
async def test_planned_works_of_other_streets_are_dropped(client: ToeClient) -> None:
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=PLANNED), httpx.Response(200, json=[])]
    )

    works = await client.planned_works(1032, 10057, NOW)

    assert [work.id for work in works] == [1571]


@respx.mock
async def test_planned_works_with_an_unexpected_shape_raise_schema_error(
    client: ToeClient,
) -> None:
    respx.get(f"{API}/pw_accident_planeds").respond(json=[{"id": 1}])
    with pytest.raises(ApiSchemaError):
        await client.planned_works(1032, LIFT_STREET_ID, NOW)


@respx.mock
async def test_a_malformed_planned_work_is_skipped_not_the_whole_street(client: ToeClient) -> None:
    broken = copy.deepcopy(PLANNED[0]) | {"datePlanIn": None, "id": 9}
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[broken, PLANNED[0]]), httpx.Response(200, json=[])]
    )

    works = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert [work.id for work in works] == [2421]


@respx.mock
async def test_a_real_time_offset_breaks_the_wall_clock_assumption_and_is_skipped(
    client: ToeClient,
) -> None:
    shifted = copy.deepcopy(PLANNED[0]) | {"dateEvent": "2026-08-22T08:30:00+03:00"}
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[shifted]), httpx.Response(200, json=[])]
    )

    assert await client.planned_works(1032, LIFT_STREET_ID, NOW) == []


@respx.mock
async def test_a_long_planned_work_reason_is_cut(client: ToeClient) -> None:
    wordy = copy.deepcopy(PLANNED[0]) | {"koment": "ремонт " * 200}
    respx.get(f"{API}/pw_accident_planeds").mock(
        side_effect=[httpx.Response(200, json=[wordy]), httpx.Response(200, json=[])]
    )

    (work,) = await client.planned_works(1032, LIFT_STREET_ID, NOW)

    assert len(work.reason) <= 300
    assert work.reason.endswith("…")

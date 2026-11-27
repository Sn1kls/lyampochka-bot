from collections.abc import AsyncIterator
from datetime import date, datetime

import pytest
import respx

from poweron.adapters.hoe_api.client import HoeClient, _search_term
from poweron.adapters.hoe_api.schedule import SUBQUEUES, parse_archive, parse_post
from poweron.core.domain.models import KYIV, Address, City
from poweron.core.ports import ApiSchemaError, SourceUnavailable
from tests.conftest import FIXTURES
from tests.fakes import FakeClock, blocks

SITE = "https://hoe.com.ua"
ARCHIVE_URL = f"{SITE}/page/arhiv-grafikiv-pogodinnih-vidkljuchen-2026"
POST_26_URL = f"{SITE}/post/prognoz-gpv-na-26-listopada.html"
POST_27_URL = f"{SITE}/post/prognoz-gpv-na-27-listopada.html"
ADDRESS = Address(city_id=25601, street_id=329329, building_name="21")
NOW = datetime(2026, 11, 27, 18, 0, tzinfo=KYIV)


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def post(*blocks_html: str) -> str:
    return '<main><div class="post">' + "<hr />".join(blocks_html) + "</div></main>"


def full_list(*lines: str) -> str:
    return "<p>Години відсутності електроенергії:</p>" + "".join(f"<p>{line}</p>" for line in lines)


def addition(*lines: str) -> str:
    return "<p>Додаткові години відсутності електроенергії:</p>" + "".join(
        f"<p>{line}</p>" for line in lines
    )


def test_a_full_list_with_an_addition_on_top() -> None:
    subqueues = parse_post(fixture_text("hoe_post_addition.html"))

    assert subqueues.keys() == SUBQUEUES
    assert blocks(subqueues["1.1"]) == [
        ("06:00", "08:00"),
        ("11:00", "14:00"),
        ("17:00", "20:00"),
        ("22:00", "24:00"),
    ]
    # «Підчерга 6.1 - 13:00-14:00» added to «14:00-17:00; 20:00-22:00».
    assert blocks(subqueues["6.1"]) == [("13:00", "17:00"), ("20:00", "22:00")]


def test_additions_stack_and_midnight_ends_the_day() -> None:
    subqueues = parse_post(fixture_text("hoe_post_two_additions.html"))

    assert blocks(subqueues["2.1"]) == [("12:00", "17:00"), ("20:00", "22:00")]
    assert blocks(subqueues["4.2"]) == [("07:00", "12:00"), ("16:00", "20:00"), ("22:00", "24:00")]
    assert blocks(subqueues["6.2"]) == [("00:00", "01:00"), ("10:00", "14:00"), ("18:00", "22:00")]
    assert blocks(subqueues["1.1"]) == [("04:00", "07:00"), ("12:00", "16:00"), ("19:00", "22:00")]


def test_the_newest_full_list_replaces_the_older_ones() -> None:
    subqueues = parse_post(fixture_text("hoe_post_five_updates.html"))

    assert blocks(subqueues["1.1"]) == [("10:30", "15:00"), ("20:00", "24:00")]
    assert blocks(subqueues["6.1"]) == [("07:30", "11:00"), ("15:00", "17:00"), ("19:00", "22:00")]


def test_a_subqueue_left_out_of_a_full_list_has_no_outages() -> None:
    subqueues = parse_post(
        post(full_list("Підчерга 1.1 – 19:00-22:00.", "Підчерга 2.1 – вимкнень немає."))
    )

    assert blocks(subqueues["1.1"]) == [("19:00", "22:00")]
    assert blocks(subqueues["2.1"]) == []
    assert blocks(subqueues["6.2"]) == []


def test_partial_full_lists_of_the_site() -> None:
    subqueues = parse_post(fixture_text("hoe_post_partial.html"))

    assert blocks(subqueues["6.1"]) == [("17:30", "19:00"), ("22:00", "24:00")]
    assert blocks(subqueues["2.1"]) == [("19:00", "22:00")]


def test_the_text_below_the_newest_list_is_not_read() -> None:
    subqueues = parse_post(
        post(full_list("Підчерга 1.1 – 10:00-12:00."), "<p>Будь-що, навіть Підчерга 9.9</p>")
    )

    assert blocks(subqueues["1.1"]) == [("10:00", "12:00")]


@pytest.mark.parametrize(
    "page",
    [
        "<main>no post</main>",
        post("<p>Графіки погодинних відключень не застосовуватимуться.</p>"),
        post(addition("Підчерга 1.1 – 10:00-12:00.")),  # an addition with nothing below it
        post(addition(), full_list("Підчерга 1.1 – 10:00-12:00.")),
        # A block above the newest list that is neither kind: a cancelled schedule, say.
        post("<p>Графік скасовано.</p>", full_list("Підчерга 1.1 – 10:00-12:00.")),
        post(full_list("Підчерга 1.1 – світла не буде.")),
        post(full_list("Підчерга 1.1 – 10:15-12:00.")),
        post(full_list("Підчерга 1.1 – 12:00-10:00.")),
        post(full_list("Підчерга 1.1 – 00:00-00:00.")),
        post(full_list("Підчерга 1.1 – 10:00-12:00.", "Підчерга 1.1 – 14:00-16:00.")),
    ],
)
def test_anything_else_is_a_schema_error(page: str) -> None:
    with pytest.raises(ApiSchemaError):
        parse_post(page)


def test_archive_links_by_day() -> None:
    entries = parse_archive(fixture_text("hoe_archive.html"), SITE)

    assert entries[date(2026, 11, 27)] == [f"{SITE}/post/prognoz-gpv-na-27-listopada.html"]
    # Each October update was a picture of its own.
    assert len(entries[date(2026, 10, 17)]) == 4
    assert entries[date(2026, 10, 17)][0].startswith(f"{SITE}/Content/Uploads/")


def test_an_archive_with_no_entries_is_a_schema_error() -> None:
    with pytest.raises(ApiSchemaError):
        parse_archive("<main></main>", SITE)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
async def client(clock: FakeClock) -> AsyncIterator[HoeClient]:
    hoe_client = HoeClient(now=lambda: NOW, monotonic=clock.monotonic, sleep=clock.sleep)
    yield hoe_client
    await hoe_client.aclose()


def mock_schedules() -> tuple[respx.Route, respx.Route]:
    archive = respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    post_route = respx.get(POST_27_URL).respond(text=fixture_text("hoe_post_addition.html"))
    return archive, post_route


@respx.mock
async def test_todays_schedule_comes_from_its_post(client: HoeClient) -> None:
    mock_schedules()

    schedules = await client.fetch_schedules(ADDRESS, "hoe:6.1")

    assert [schedule.day for schedule in schedules] == [date(2026, 11, 27)]  # no 28.11 post yet
    assert schedules[0].cherg_gpv == "hoe:6.1"
    assert schedules[0].created_at == NOW
    assert schedules[0].slots["13:00"] == "1"
    assert schedules[0].slots["12:30"] == "0"


@respx.mock
async def test_one_pass_serves_every_subqueue_for_a_minute(
    client: HoeClient, clock: FakeClock
) -> None:
    archive, post_route = mock_schedules()

    await client.fetch_schedules(ADDRESS, "hoe:6.1")
    await client.fetch_schedules(ADDRESS, "hoe:1.1")
    clock.monotonic_now += 61
    again = await client.fetch_schedules(ADDRESS, "hoe:1.1")

    assert archive.call_count == post_route.call_count == 2
    assert again[0].created_at == NOW  # the same text keeps the time it was first seen


@respx.mock
async def test_tomorrow_is_read_from_its_own_post(clock: FakeClock) -> None:
    respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    respx.get(POST_26_URL).respond(text=fixture_text("hoe_post_partial.html"))
    respx.get(POST_27_URL).respond(text=fixture_text("hoe_post_addition.html"))
    before = datetime(2026, 11, 26, 21, 0, tzinfo=KYIV)
    hoe_client = HoeClient(now=lambda: before, monotonic=clock.monotonic, sleep=clock.sleep)

    schedules = await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")
    await hoe_client.aclose()

    assert [schedule.day for schedule in schedules] == [date(2026, 11, 26), date(2026, 11, 27)]


@respx.mock
async def test_a_broken_tomorrow_does_not_hide_today(clock: FakeClock) -> None:
    respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    respx.get(POST_26_URL).respond(text=fixture_text("hoe_post_partial.html"))
    respx.get(POST_27_URL).respond(text=post("<p>Графік скасовано.</p>"))
    before = datetime(2026, 11, 26, 21, 0, tzinfo=KYIV)
    hoe_client = HoeClient(now=lambda: before, monotonic=clock.monotonic, sleep=clock.sleep)

    schedules = await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")
    await hoe_client.aclose()

    assert [schedule.day for schedule in schedules] == [date(2026, 11, 26)]


@respx.mock
async def test_a_broken_today_is_an_error_even_with_tomorrow_fine(clock: FakeClock) -> None:
    respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    respx.get(POST_26_URL).respond(text=post("<p>Графік скасовано.</p>"))
    respx.get(POST_27_URL).respond(text=fixture_text("hoe_post_addition.html"))
    before = datetime(2026, 11, 26, 21, 0, tzinfo=KYIV)
    hoe_client = HoeClient(now=lambda: before, monotonic=clock.monotonic, sleep=clock.sleep)

    with pytest.raises(ApiSchemaError):
        await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")
    await hoe_client.aclose()


@respx.mock
async def test_an_addition_redates_only_its_subqueues(clock: FakeClock) -> None:
    respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    post_route = respx.get(POST_27_URL)
    base = fixture_text("hoe_post_addition.html").split("<hr />", 1)[1]
    post_route.respond(text='<div class="post">' + base)
    now = NOW
    hoe_client = HoeClient(now=lambda: now, monotonic=clock.monotonic, sleep=clock.sleep)
    await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")

    now = NOW.replace(hour=19)
    post_route.respond(text=fixture_text("hoe_post_addition.html"))  # adds 13:00-14:00 to 6.1
    clock.monotonic_now += 61
    changed = await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")
    untouched = await hoe_client.fetch_schedules(ADDRESS, "hoe:1.1")
    await hoe_client.aclose()

    assert changed[0].created_at == now
    assert untouched[0].created_at == NOW


@respx.mock
async def test_a_day_of_pictures_is_a_schema_error(clock: FakeClock) -> None:
    respx.get(ARCHIVE_URL).respond(text=fixture_text("hoe_archive.html"))
    october = datetime(2026, 10, 17, 18, 0, tzinfo=KYIV)
    hoe_client = HoeClient(now=lambda: october, monotonic=clock.monotonic, sleep=clock.sleep)

    with pytest.raises(ApiSchemaError):
        await hoe_client.fetch_schedules(ADDRESS, "hoe:6.1")
    await hoe_client.aclose()


@respx.mock
async def test_an_unknown_subqueue_has_no_schedule(client: HoeClient) -> None:
    assert await client.fetch_schedules(ADDRESS, "hoe:7.1") == []


@respx.mock
async def test_settlements_keep_the_hromada_apart(client: HoeClient) -> None:
    route = respx.get(f"{SITE}/settlements/").respond(
        text=fixture_text("hoe_settlements.json"), headers={"content-type": "application/json"}
    )

    cities = await client.search_cities("м. Камʼянець")

    assert cities == [
        City(id=25601, name="м. Кам'янець-Подільський", otg_name="Кам’янець-Подільська громада")
    ]
    request = route.calls.last.request
    assert request.url.params["term"] == "янець"
    assert request.headers["X-Requested-With"] == "XMLHttpRequest"


@respx.mock
async def test_streets_and_houses(client: HoeClient) -> None:
    respx.get(f"{SITE}/streets/25601").respond(
        text=fixture_text("hoe_streets.json"), headers={"content-type": "application/json"}
    )
    respx.get(f"{SITE}/houses/329329").respond(
        text=fixture_text("hoe_houses.json"), headers={"content-type": "application/json"}
    )

    streets = await client.search_streets(25601, "Шевч")
    buildings = await client.buildings(25601, 329329)

    assert "вул. Шевченка" in [street.name for street in streets]
    assert len(buildings) == 139
    assert all(building.cherg_gpv is None for building in buildings)
    assert len({building.id for building in buildings}) == 139


@pytest.mark.parametrize(
    ("house", "subqueues"), [("21", ["hoe:4.1", "hoe:5.1"]), ("45", ["hoe:3.1"]), ("1", [])]
)
@respx.mock
async def test_a_houses_subqueues(client: HoeClient, house: str, subqueues: list[str]) -> None:
    route = respx.post(f"{SITE}/shutdown-queues").respond(
        text=fixture_text(f"hoe_queues_{house}.html")
    )

    assert await client.building_subqueues(25601, 329329, house) == subqueues
    assert route.calls.last.request.content == f"streetId=329329&house={house}".encode()


@respx.mock
async def test_an_empty_subqueue_means_none(client: HoeClient) -> None:
    respx.post(f"{SITE}/shutdown-queues").respond(text="підчерги: <strong> </strong>")

    assert await client.building_subqueues(25601, 329329, "21") == []


@pytest.mark.parametrize("answer", ["<div>nothing</div>", "підчерги: <strong>7.1</strong>"])
@respx.mock
async def test_an_unexpected_queue_answer_is_a_schema_error(client: HoeClient, answer: str) -> None:
    respx.post(f"{SITE}/shutdown-queues").respond(text=answer)

    with pytest.raises(ApiSchemaError):
        await client.building_subqueues(25601, 329329, "21")


@respx.mock
async def test_the_sites_404_page_is_unavailable(client: HoeClient) -> None:
    respx.get(f"{SITE}/streets/25601").respond(404, text="<html>Помилка 404</html>")

    with pytest.raises(SourceUnavailable):
        await client.search_streets(25601, "Шевч")


@pytest.mark.parametrize(
    ("query", "term"),
    [
        ("вул. Шевч", "шевч"),
        ("Кам'янець-Подільський", "янець-подільський"),
        ("Хмельницький", "хмельницький"),
        ("  ", ""),
        ("Xмельницький", "хмельницький"),  # a Latin X typed for the Cyrillic one
        ("c. Гуків", "гуків"),  # a Latin c in the type prefix
    ],
)
def test_search_terms(query: str, term: str) -> None:
    assert _search_term(query) == term

import logging
from datetime import date, datetime, timedelta

import pytest

from poweron.core.domain.models import KYIV, Interval, SlotState
from poweron.core.domain.schedule import merge, parse_slots
from tests.conftest import load_fixture

ON, OFF, SWITCHING, UNKNOWN = SlotState.ON, SlotState.OFF, SlotState.SWITCHING, SlotState.UNKNOWN
DAY = date(2026, 10, 17)


def kyiv_time(day: date, wall_time: str) -> datetime:
    if wall_time == "24:00":
        return datetime.combine(day + timedelta(days=1), datetime.min.time(), KYIV)
    hour, minute = map(int, wall_time.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KYIV)


def spans(intervals: list[Interval], day: date = DAY) -> list[tuple[str, str, SlotState]]:
    def label(moment: datetime) -> str:
        local = moment.astimezone(KYIV)
        return "24:00" if local.date() > day else f"{local:%H:%M}"

    return [(label(interval.start), label(interval.end), interval.state) for interval in intervals]


def all_on() -> dict[str, str]:
    return {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}


def test_fixture_matches_site_rendering() -> None:
    # Hand-checked against the site screenshot (docs/api-notes.md).
    member = load_fixture("a_gpv_g_4.1_2026-10-17.json")["hydra:member"][0]
    times = member["dataJson"]["4.1"]["times"]

    assert spans(parse_slots(times, DAY)) == [
        ("00:00", "10:30", ON),
        ("10:30", "11:00", SWITCHING),
        ("11:00", "14:00", OFF),
        ("14:00", "14:30", SWITCHING),
        ("14:30", "19:30", ON),
        ("19:30", "20:00", SWITCHING),
        ("20:00", "22:00", OFF),
        ("22:00", "22:30", SWITCHING),
        ("22:30", "24:00", ON),
    ]


def test_day_without_outages_is_one_interval() -> None:
    [interval] = parse_slots(all_on(), DAY)
    assert (interval.start, interval.end, interval.state) == (
        kyiv_time(DAY, "00:00"),
        kyiv_time(DAY, "24:00"),
        ON,
    )


def test_unknown_value_is_kept_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    times = all_on() | {"12:00": "7"}
    with caplog.at_level(logging.WARNING):
        result = parse_slots(times, DAY)
    assert ("12:00", "12:30", UNKNOWN) in spans(result)
    assert "7" in caplog.text


def test_missing_slot_is_unknown(caplog: pytest.LogCaptureFixture) -> None:
    times = all_on()
    del times["12:00"]
    with caplog.at_level(logging.WARNING):
        result = parse_slots(times, DAY)
    assert ("12:00", "12:30", UNKNOWN) in spans(result)
    assert "12:00" in caplog.text


def test_unknown_slots_are_logged_once_per_day(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        parse_slots({}, DAY)
    assert len(caplog.records) == 1


def test_semantics_table_is_configurable() -> None:
    times = all_on() | {"12:00": "1"}
    result = parse_slots(times, DAY, semantics={"0": OFF, "1": ON})
    assert spans(result) == [
        ("00:00", "12:00", OFF),
        ("12:00", "12:30", ON),
        ("12:30", "24:00", OFF),
    ]


def test_outage_through_midnight_is_merged_across_days() -> None:
    tomorrow = DAY + timedelta(days=1)
    today = parse_slots(all_on() | {"23:30": "1"}, DAY)
    next_day = parse_slots(all_on() | {"00:00": "1", "00:30": "1"}, tomorrow)

    merged = merge(today + next_day)

    assert Interval(kyiv_time(DAY, "23:30"), kyiv_time(tomorrow, "01:00"), OFF) in merged
    assert len(merged) == 3


def test_spring_forward_gap_slots_are_skipped() -> None:
    # 2027-03-28 03:00 Kyiv jumps to 04:00: slots 03:00 and 03:30 do not exist.
    day = date(2027, 3, 28)
    times = all_on() | {"02:30": "1", "03:00": "1", "03:30": "1", "04:00": "10"}
    result = parse_slots(times, day)

    off = next(interval for interval in result if interval.state is OFF)
    assert off.end - off.start == timedelta(minutes=30)
    assert result[-1].end - result[0].start == timedelta(hours=23)


def test_fall_back_repeats_the_0300_hour() -> None:
    # 2026-10-25 04:00 Kyiv goes back to 03:00: the 03:xx slots happen twice.
    day = date(2026, 10, 25)
    result = parse_slots(all_on() | {"03:30": "1"}, day)

    offs = [interval for interval in result if interval.state is OFF]
    assert [interval.end - interval.start for interval in offs] == [timedelta(minutes=30)] * 2
    assert result[-1].end - result[0].start == timedelta(hours=25)

import json
from datetime import date

from poweron.core.domain.diff import data_hash, schedule_change
from poweron.core.domain.models import KYIV, Interval, SlotState

DAY = date(2026, 10, 17)


def slots(overrides: dict[str, str]) -> dict[str, str]:
    base = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    return base | overrides


def test_hash_ignores_key_order_and_sees_any_value_change() -> None:
    times = slots({"11:00": "1"})
    assert data_hash(times) == data_hash(dict(reversed(times.items())))
    assert data_hash(times) != data_hash(slots({"11:00": "10"}))


def test_same_outages_are_no_change() -> None:
    assert schedule_change("4.1", DAY, slots({"11:00": "1"}), slots({"11:00": "1"})) is None


def kyiv_spans(intervals: list[Interval]) -> list[tuple[str, str, SlotState]]:
    return [
        (
            f"{interval.start.astimezone(KYIV):%H:%M}",
            f"{interval.end.astimezone(KYIV):%H:%M}",
            interval.state,
        )
        for interval in intervals
    ]


def test_moved_outage_is_reported_as_added_and_removed() -> None:
    change = schedule_change("4.1", DAY, slots({"11:00": "1"}), slots({"12:00": "1"}))

    assert change is not None
    assert kyiv_spans(change.removed) == [("11:00", "11:30", SlotState.OFF)]
    assert kyiv_spans(change.added) == [("12:00", "12:30", SlotState.OFF)]


def test_new_day_has_no_previous_and_everything_is_added() -> None:
    change = schedule_change("4.1", DAY, None, slots({"11:00": "1"}))

    assert change is not None
    assert change.previous is None
    assert change.added == change.current
    assert change.removed == []


def test_payload_is_plain_json() -> None:
    change = schedule_change("4.1", DAY, slots({"11:00": "1"}), slots({"12:00": "10"}))
    assert change is not None

    payload = json.loads(json.dumps(change.payload()))

    assert payload["cherg_gpv"] == "4.1"
    assert payload["day"] == "2026-10-17"
    assert payload["removed"] == [
        {"start": "2026-10-17T08:00:00+00:00", "end": "2026-10-17T08:30:00+00:00", "state": "off"}
    ]
    assert payload["added"][0]["state"] == "switching"

from datetime import UTC, date, datetime

from poweron.adapters.telegram.render import render_day, render_next, render_update
from poweron.core.domain.diff import schedule_change
from poweron.core.domain.models import (
    KYIV,
    Address,
    DayView,
    NextEvent,
    Subscription,
)
from poweron.core.domain.schedule import parse_slots
from tests.conftest import load_fixture

DAY = date(2026, 10, 17)
TOMORROW = date(2026, 10, 18)
NOTE = "Графік може змінюватись упродовж дня. Орієнтуйтесь також на poweron.toe.com.ua"
LINK = '<a href="https://poweron.toe.com.ua">poweron.toe.com.ua</a>'
PUBLISHED = datetime(2026, 10, 17, 14, 16, 5, tzinfo=UTC)

SUBSCRIPTION = Subscription(
    id=1,
    user_id=1,
    label="Дім <&>",
    address=Address(1, 2, "5"),
    city_name="Тернопіль",
    street_name="Руська",
    building_id=3,
    cherg_gpv="4.1#7",
    notify_on_update=True,
    remind_before_off_min=0,
    remind_before_on_min=0,
    created_at=PUBLISHED,
)


def fixture_slots() -> dict[str, str]:
    return load_fixture("a_gpv_g_4.1_2026-10-17.json")["hydra:member"][0]["dataJson"]["4.1"][
        "times"
    ]


def test_render_day_lists_kyiv_intervals_with_total_outage() -> None:
    view = DayView(DAY, parse_slots(fixture_slots(), DAY), PUBLISHED, PUBLISHED)

    assert render_day(SUBSCRIPTION, view, DAY, today=DAY) == "\n".join(
        [
            "💡 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
            "Підчерга 4.1 · оновлено 17.10 14:16",
            "",
            "🟢 00:00–10:30 є світло",
            "🟡 10:30–11:00 можливе відключення (перемикання)",
            "🔴 11:00–14:00 немає світла",
            "🟡 14:00–14:30 можливе відключення (перемикання)",
            "🟢 14:30–19:30 є світло",
            "🟡 19:30–20:00 можливе відключення (перемикання)",
            "🔴 20:00–22:00 немає світла",
            "🟡 22:00–22:30 можливе відключення (перемикання)",
            "🟢 22:30–24:00 є світло",
            "",
            "Разом без світла: 5 год",
            "",
            NOTE,
        ]
    )


def test_render_day_without_tomorrow_says_it_is_not_published_yet() -> None:
    assert render_day(SUBSCRIPTION, None, TOMORROW, today=DAY) == "\n\n".join(
        [
            "💡 <b>Дім &lt;&amp;&gt;</b>, завтра (18.10)",
            "Графіка на завтра ще немає — щойно з'явиться, напишу.",
            NOTE,
        ]
    )


def test_render_next_power_off_and_on() -> None:
    now = datetime(2026, 10, 17, 9, 0, tzinfo=KYIV)
    off = NextEvent(datetime(2026, 10, 17, 11, 30, tzinfo=KYIV), power_on=False)
    on = NextEvent(datetime(2026, 10, 17, 9, 45, tzinfo=KYIV), power_on=True)

    assert render_next(SUBSCRIPTION, off, now) == (
        "<b>Дім &lt;&amp;&gt;</b>: світло вимкнуть о 11:30 (через 2 год 30 хв)"
    )
    assert render_next(SUBSCRIPTION, on, now) == (
        "<b>Дім &lt;&amp;&gt;</b>: світло увімкнуть о 09:45 (через 45 хв)"
    )
    assert "змін не заплановано" in render_next(SUBSCRIPTION, None, now)


def update_payload(previous: dict[str, str] | None, current: dict[str, str]) -> dict[str, object]:
    change = schedule_change("4.1", DAY, previous, current)
    assert change is not None
    return change.payload() | {"label": "Дім", "subscription_id": 1}


def test_render_update_for_a_change_shows_added_and_removed() -> None:
    previous = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    current = previous | {"10:00": "1", "10:30": "1"}
    changed = current | {"10:00": "0", "10:30": "0", "18:00": "1"}
    payload = update_payload(current, changed)

    assert render_update(payload) == "\n\n".join(
        [
            "💡 Графік для <b>Дім</b> оновлено",
            "Зміни на 17.10:",
            "Додано:\n🔴 18:00–18:30 немає світла",
            "Прибрано:\n🔴 10:00–11:00 немає світла",
            LINK,
        ]
    )


def test_render_update_for_new_tomorrow() -> None:
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    outage = slots | {"23:00": "1", "23:30": "1"}

    assert render_update(update_payload(None, outage)) == "\n\n".join(
        [
            "💡 Графік для <b>Дім</b> оновлено",
            "З'явився графік на 17.10:",
            "🔴 23:00–24:00 немає світла",
            LINK,
        ]
    )
    assert render_update(update_payload(None, slots) | {"current": []}).splitlines()[2] == (
        "З'явився графік на 17.10: без відключень 🎉"
    )

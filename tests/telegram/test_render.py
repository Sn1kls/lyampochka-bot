from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from poweron.adapters.telegram import texts
from poweron.adapters.telegram.render import (
    render_confirm,
    render_day,
    render_list,
    render_next,
    render_planned_work,
    render_queues,
    render_reminder,
    render_settings,
    render_subqueues_changed,
    render_update,
    subqueue_label,
)
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
NOTE = "Графік може змінюватися впродовж дня, тож поглядай і на poweron.toe.com.ua"
LINK = '<a href="https://poweron.toe.com.ua">poweron.toe.com.ua</a>'
PUBLISHED = datetime(2026, 10, 17, 14, 16, 5, tzinfo=UTC)
NOW = datetime(2026, 10, 17, 14, 20, tzinfo=UTC)

SUBSCRIPTION = Subscription(
    id=1,
    user_id=1,
    label="Дім <&>",
    address=Address(1, 2, "5"),
    city_name="Тернопіль",
    street_name="Руська",
    building_id=3,
    subqueues=("4.1#7",),
    tracked_subqueues=("4.1#7",),
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
    view = DayView("4.1#7", DAY, parse_slots(fixture_slots(), DAY), PUBLISHED, PUBLISHED)

    assert render_day(SUBSCRIPTION, [view], DAY, NOW) == "\n".join(
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
            "Разом без світла: 5 год (до 7 год з перемиканнями)",
            "",
            NOTE,
        ]
    )


def test_render_day_with_two_queues_has_a_block_per_queue_and_one_note() -> None:
    subscription = replace(SUBSCRIPTION, subqueues=("2.2", "4.1"), tracked_subqueues=("2.2", "4.1"))
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    first = DayView(
        "2.2", DAY, parse_slots(slots | {"10:00": "1", "10:30": "1"}, DAY), PUBLISHED, PUBLISHED
    )
    second = DayView("4.1", DAY, parse_slots(slots, DAY), PUBLISHED, PUBLISHED)

    text = render_day(subscription, [first, second], DAY, NOW)

    assert text == "\n".join(
        [
            "💡 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
            "",
            "Підчерга 2.2 · оновлено 17.10 14:16",
            "🟢 00:00–10:00 є світло",
            "🔴 10:00–11:00 немає світла",
            "🟢 11:00–24:00 є світло",
            "",
            "Разом без світла: 1 год",
            "",
            "Підчерга 4.1 · оновлено 17.10 14:16",
            "🟢 00:00–24:00 є світло",
            "",
            "Відключень не заплановано 🎉",
            "",
            NOTE,
        ]
    )


def test_render_queues_marks_tracked_ones_only_when_some_are_not() -> None:
    assert render_queues(("2.2", "4.1"), ("2.2", "4.1")) == "черги 2.2 і 4.1"
    assert render_queues(("4.1", "2.2"), ("4.1",)) == "черги 4.1 (стежу), 2.2"
    assert render_queues(("4.1",), ("4.1",)) == "підчерга 4.1"


def test_confirm_text_shows_every_queue_of_the_building() -> None:
    both = render_confirm("Тернопіль", "Руська", "96", ("2.2", "4.1"), ("2.2", "4.1"), "Дім")
    one = render_confirm("Тернопіль", "Руська", "5", ("4.1",), ("4.1",), "Дім")

    assert both.splitlines()[:2] == ["<b>Тернопіль, Руська, 96</b>", "Черги 2.2 і 4.1"]
    assert one.splitlines()[:2] == ["<b>Тернопіль, Руська, 5</b>", "Підчерга 4.1"]


def test_render_update_names_the_queue_only_when_several_are_tracked() -> None:
    payload = update_payload(
        None, {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    )

    assert render_update(payload | {"queue_count": 2}).startswith(
        "💡 Графік для <b>Дім</b> (черга 4.1) оновлено"
    )
    assert render_update(payload | {"queue_count": 1}).startswith(
        "💡 Графік для <b>Дім</b> оновлено"
    )


def test_render_day_total_has_no_switching_suffix_without_switching() -> None:
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    view = DayView(
        "4.1#7", DAY, parse_slots(slots | {"10:00": "1", "10:30": "1"}, DAY), PUBLISHED, PUBLISHED
    )

    assert "Разом без світла: 1 год\n" in render_day(SUBSCRIPTION, [view], DAY, NOW) + "\n"


def test_render_day_without_tomorrow_says_it_is_not_published_yet() -> None:
    assert render_day(SUBSCRIPTION, [], TOMORROW, NOW) == "\n\n".join(
        [
            "💡 <b>Дім &lt;&amp;&gt;</b>, завтра (18.10)",
            "Графіка на завтра ще немає — щойно з'явиться, напишу.",
            NOTE,
        ]
    )


def test_render_day_warns_when_the_data_was_last_checked_long_ago() -> None:
    view = DayView("4.1#7", DAY, parse_slots(fixture_slots(), DAY), PUBLISHED, PUBLISHED)
    fresh = render_day(SUBSCRIPTION, [view], DAY, PUBLISHED + timedelta(minutes=30))
    stale = render_day(SUBSCRIPTION, [view], DAY, PUBLISHED + timedelta(minutes=31))

    warning = "⚠️ Дані могли застаріти: востаннє з сайту оновлено 17.10 17:16."
    assert warning not in fresh
    assert stale.splitlines()[:5] == [
        "💡 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
        "Підчерга 4.1 · оновлено 17.10 14:16",
        "",
        warning,
        "",
    ]


def test_render_day_derives_today_in_kyiv_from_now() -> None:
    late_evening = datetime(2026, 10, 17, 21, 30, tzinfo=UTC)  # already 18.10 in Kyiv

    assert "сьогодні (18.10)" in render_day(SUBSCRIPTION, [], TOMORROW, late_evening)


def test_subqueue_label_is_escaped_everywhere() -> None:
    queue = "<b>4.1</b>#7"
    subscription = replace(SUBSCRIPTION, subqueues=(queue,), tracked_subqueues=(queue,))
    view = DayView(queue, DAY, parse_slots(fixture_slots(), DAY), PUBLISHED, PUBLISHED)

    assert subqueue_label(queue) == "&lt;b&gt;4.1&lt;/b&gt;"
    assert "Підчерга &lt;b&gt;4.1&lt;/b&gt; ·" in render_day(subscription, [view], DAY, NOW)
    assert "(підчерга &lt;b&gt;4.1&lt;/b&gt;)" in render_list([subscription])


def test_render_list_shows_one_escaped_address_per_subscription() -> None:
    assert render_list([SUBSCRIPTION]) == "\n".join(
        ["Твої адреси:", "• <b>Дім &lt;&amp;&gt;</b> — Тернопіль, Руська, 5 (підчерга 4.1)"]
    )


def kyiv_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 17, hour, minute, tzinfo=KYIV)


@pytest.mark.parametrize(
    ("event", "now", "expected"),
    [
        (
            NextEvent(False, kyiv_time(11, 30), kyiv_time(11, 30)),
            kyiv_time(9),
            "світло вимкнуть о 11:30 (через 2 год 30 хв)",
        ),
        (
            NextEvent(False, kyiv_time(10, 30), kyiv_time(11)),
            kyiv_time(9),
            "світло можуть вимкнути з 10:30, точно — о 11:00 (через 1 год 30 хв)",
        ),
        (
            NextEvent(False, kyiv_time(10, 30), None),
            kyiv_time(9),
            "можливе вимкнення з 10:30 (перемикання)",
        ),
        (
            NextEvent(True, kyiv_time(9, 45), kyiv_time(9, 45)),
            kyiv_time(9),
            "світло увімкнуть о 09:45 (через 45 хв)",
        ),
        (
            NextEvent(True, kyiv_time(14), kyiv_time(14, 30)),
            kyiv_time(12),
            "світло можуть увімкнути з 14:00, точно — о 14:30 (через 2 год)",
        ),
        (
            NextEvent(True, kyiv_time(14, 10), kyiv_time(14, 30)),
            kyiv_time(14, 10),
            "світло можуть дати будь-якої хвилини, точно — о 14:30",
        ),
    ],
)
def test_render_next_shows_earliest_and_guaranteed_times(
    event: NextEvent, now: datetime, expected: str
) -> None:
    assert render_next(SUBSCRIPTION, [("4.1#7", event)], now) == (
        f"<b>Дім &lt;&amp;&gt;</b>: {expected}"
    )


def test_render_next_without_an_event() -> None:
    assert "змін не заплановано" in render_next(SUBSCRIPTION, [], kyiv_time(9))


def test_render_next_lists_each_tracked_queue() -> None:
    subscription = replace(SUBSCRIPTION, subqueues=("2.2", "4.1"), tracked_subqueues=("2.2", "4.1"))
    events = [
        ("2.2", NextEvent(False, kyiv_time(11, 30), kyiv_time(11, 30))),
        ("4.1", NextEvent(True, kyiv_time(9, 45), kyiv_time(9, 45))),
    ]

    assert render_next(subscription, events, kyiv_time(9)) == "\n".join(
        [
            "<b>Дім &lt;&amp;&gt;</b>:",
            "• підчерга 2.2: світло вимкнуть о 11:30 (через 2 год 30 хв)",
            "• підчерга 4.1: світло увімкнуть о 09:45 (через 45 хв)",
        ]
    )


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
            NOTE,
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
            NOTE,
            LINK,
        ]
    )
    assert render_update(update_payload(None, slots) | {"current": []}).splitlines()[2] == (
        "З'явився графік на 17.10: без відключень 🎉"
    )


def test_day_with_only_switching_is_not_a_zero_outage() -> None:
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    view = DayView("4.1#7", DAY, parse_slots(slots | {"12:00": "10"}, DAY), PUBLISHED, PUBLISHED)

    text = render_day(SUBSCRIPTION, [view], DAY, NOW)

    assert texts.ONLY_SWITCHING.format(duration="30 хв") in text
    assert "Разом без світла" not in text


def test_a_tracked_queue_without_data_yet_is_shown_not_dropped() -> None:
    subscription = replace(SUBSCRIPTION, subqueues=("2.2", "4.1"), tracked_subqueues=("2.2", "4.1"))
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    only_second = DayView("4.1", DAY, parse_slots(slots, DAY), PUBLISHED, PUBLISHED)

    text = render_day(subscription, [only_second], DAY, NOW)

    assert f"Підчерга 2.2\n{texts.QUEUE_NOT_LOADED}" in text
    assert text.index("Підчерга 2.2") < text.index("Підчерга 4.1")


def test_viewing_one_untracked_queue_shows_only_that_queue() -> None:
    subscription = replace(SUBSCRIPTION, subqueues=("4.1", "2.2"), tracked_subqueues=("4.1",))

    text = render_day(subscription, [], DAY, NOW, queues=["2.2"])

    assert "Підчерга 2.2" in text
    assert "4.1" not in text


def reminder_payload(**changes: object) -> dict[str, object]:
    return {
        "subscription_id": 1,
        "label": "Дім <&>",
        "cherg_gpv": "4.1#7",
        "queue_count": 1,
        "minutes": 15,
        "earliest": "2026-10-17T07:00:00+00:00",
        "latest": "2026-10-17T07:30:00+00:00",
        **changes,
    }


@pytest.mark.parametrize(
    ("payload", "power_on", "expected"),
    [
        (
            reminder_payload(),
            False,
            "⏰ <b>Дім &lt;&amp;&gt;</b>: за 15 хв можуть вимкнути світло (з 10:00, точно — о 10:30)",
        ),
        (
            reminder_payload(latest="2026-10-17T07:00:00+00:00"),
            False,
            "⏰ <b>Дім &lt;&amp;&gt;</b>: за 15 хв вимкнуть світло (о 10:00)",
        ),
        (
            reminder_payload(latest=None),
            False,
            "⏰ <b>Дім &lt;&amp;&gt;</b>: за 15 хв можливе вимкнення з 10:00",
        ),
        (
            reminder_payload(minutes=30),
            True,
            "💡 <b>Дім &lt;&amp;&gt;</b>: за 30 хв мають дати світло (з 10:00, точно — о 10:30)",
        ),
        (
            reminder_payload(latest="2026-10-17T07:00:00+00:00"),
            True,
            "💡 <b>Дім &lt;&amp;&gt;</b>: за 15 хв дадуть світло (о 10:00)",
        ),
        (
            reminder_payload(latest=None),
            True,
            "💡 <b>Дім &lt;&amp;&gt;</b>: за 15 хв можливе повернення світла з 10:00",
        ),
        (
            reminder_payload(queue_count=2),
            False,
            "⏰ <b>Дім &lt;&amp;&gt;</b> (черга 4.1): за 15 хв можуть вимкнути світло "
            "(з 10:00, точно — о 10:30)",
        ),
        (
            reminder_payload(queue_count=2, latest="2026-10-17T07:00:00+00:00"),
            True,
            "💡 <b>Дім &lt;&amp;&gt;</b> (черга 4.1): за 15 хв дадуть світло (о 10:00)",
        ),
    ],
)
def test_render_reminder(payload: dict[str, object], power_on: bool, expected: str) -> None:
    assert render_reminder(payload, power_on=power_on) == expected


def test_render_subqueues_changed_lists_queues_and_points_to_settings() -> None:
    payload = {
        "subscription_id": 1,
        "label": "Дім <&>",
        "previous": ["4.1#7"],
        "current": ["2.2#3", "4.1#7"],
        "tracked": ["4.1#7"],
    }

    assert render_subqueues_changed(payload) == "\n".join(
        [
            "🔄 Для <b>Дім &lt;&amp;&gt;</b> змінилися черги.",
            "Було: 4.1",
            "Стало: 2.2, 4.1",
            "Стежу за: 4.1",
            "",
            "Перевір, чи все гаразд, у /settings",
        ]
    )


def test_render_subqueues_changed_says_so_when_the_schedule_no_longer_applies() -> None:
    payload = {"label": "Дім <&>", "previous": ["4.1"], "current": [], "tracked": ["4.1"]}

    text = render_subqueues_changed(payload)

    assert "<b>Дім &lt;&amp;&gt;</b>" in text
    assert "більше не діють" in text
    assert "poweron.toe.com.ua" in text
    assert "Стало" not in text


def test_render_settings_shows_each_setting() -> None:
    subscription = replace(SUBSCRIPTION, notify_on_update=False, remind_before_off_min=15)

    assert render_settings(subscription) == "\n".join(
        [
            "⚙️ Налаштування для <b>Дім &lt;&amp;&gt;</b>",
            "Пуші про оновлення графіка: вимкнено",
            "⏰ Нагадати перед вимкненням: 15 хв",
            "💡 Нагадати перед поверненням світла: без",
        ]
    )


def planned_payload(**changes: object) -> dict[str, object]:
    return {
        "subscription_id": 1,
        "label": "Дім",
        "starts_at": "2026-08-22T05:30:00+00:00",
        "ends_at": "2026-08-22T14:30:00+00:00",
        "reason": "Ремонт ПЛ",
    } | changes


def test_planned_work_shows_kyiv_times_and_reason() -> None:
    assert render_planned_work(planned_payload()) == (
        "🛠 <b>Дім</b>: планові роботи 22.08 з 08:30 до 17:30 — Ремонт ПЛ"
    )


def test_planned_work_without_reason_has_no_dash() -> None:
    assert render_planned_work(planned_payload(reason="")) == (
        "🛠 <b>Дім</b>: планові роботи 22.08 з 08:30 до 17:30"
    )


def test_planned_work_ending_on_another_day_shows_the_end_date() -> None:
    text = render_planned_work(planned_payload(ends_at="2026-08-23T14:30:00+00:00"))

    assert text.startswith("🛠 <b>Дім</b>: планові роботи 22.08 з 08:30 до 23.08 17:30")


def test_planned_work_escapes_label_and_reason() -> None:
    text = render_planned_work(planned_payload(label="<i>", reason="a < b & c"))

    assert "<b>&lt;i&gt;</b>" in text
    assert text.endswith("a &lt; b &amp; c")

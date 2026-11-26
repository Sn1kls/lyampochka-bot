from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from poweron.adapters.telegram import texts
from poweron.adapters.telegram.render import (
    render_confirm,
    render_day,
    render_emergency,
    render_list,
    render_next,
    render_planned_work,
    render_queues,
    render_reminder,
    render_settings,
    render_status,
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
    PlannedWork,
    StatusReport,
    SubqueueStatus,
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
            "📅 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
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
            "📅 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
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


def test_render_day_total_has_no_switching_suffix_without_switching() -> None:
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    view = DayView(
        "4.1#7", DAY, parse_slots(slots | {"10:00": "1", "10:30": "1"}, DAY), PUBLISHED, PUBLISHED
    )

    assert "Разом без світла: 1 год\n" in render_day(SUBSCRIPTION, [view], DAY, NOW) + "\n"


def test_render_day_without_tomorrow_says_it_is_not_published_yet() -> None:
    assert render_day(SUBSCRIPTION, [], TOMORROW, NOW) == "\n\n".join(
        [
            "📅 <b>Дім &lt;&amp;&gt;</b>, завтра (18.10)",
            "Графіка на завтра ще немає – щойно з'явиться, напишу.",
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
        "📅 <b>Дім &lt;&amp;&gt;</b>, сьогодні (17.10)",
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
        ["Твої адреси:", "• <b>Дім &lt;&amp;&gt;</b> – Тернопіль, Руська, 5 (підчерга 4.1)"]
    )


def kyiv_time(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 17, hour, minute, tzinfo=KYIV)


@pytest.mark.parametrize(
    ("event", "now", "expected"),
    [
        (
            NextEvent(False, kyiv_time(11, 30), kyiv_time(11, 30)),
            kyiv_time(9),
            "світло вимкнуть об 11:30 (через 2 год 30 хв)",
        ),
        (
            NextEvent(False, kyiv_time(10, 30), kyiv_time(11)),
            kyiv_time(9),
            "світло можуть вимкнути з 10:30, точно – об 11:00 (через 1 год 30 хв)",
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
            "світло можуть увімкнути з 14:00, точно – о 14:30 (через 2 год)",
        ),
        (
            NextEvent(True, kyiv_time(14, 10), kyiv_time(14, 30)),
            kyiv_time(14, 10),
            "світло можуть дати будь-якої хвилини, точно – о 14:30",
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
            "• підчерга 2.2: світло вимкнуть об 11:30 (через 2 год 30 хв)",
            "• підчерга 4.1: світло увімкнуть о 09:45 (через 45 хв)",
        ]
    )


def update_payload(previous: dict[str, str] | None, current: dict[str, str]) -> dict[str, object]:
    change = schedule_change("4.1", DAY, previous, current)
    assert change is not None
    return change.payload() | {"label": "Дім", "subscription_id": 1}


LIGHT_ALL_DAY = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}


def test_render_update_is_a_title_and_the_whole_day() -> None:
    previous = LIGHT_ALL_DAY | {"10:00": "1", "10:30": "1"}
    payload = update_payload(previous, LIGHT_ALL_DAY | {"18:00": "1"}) | {"address_count": 1}

    assert render_update(payload, NOW) == "\n\n".join(
        [
            "💡 Оновлення на сьогодні (17.10):",
            "🟢 00:00–18:00 є світло\n🔴 18:00–18:30 немає світла 🆕\n🟢 18:30–24:00 є світло",
            NOTE,
            LINK,
        ]
    )


def test_render_update_names_tomorrow_and_shows_a_day_without_outages() -> None:
    payload = update_payload(None, LIGHT_ALL_DAY) | {"current": [], "address_count": 1}

    assert render_update(payload, NOW - timedelta(days=1)).split("\n\n")[:2] == [
        "💡 Оновлення на завтра (17.10):",
        "🟢 00:00–24:00 є світло",
    ]


def test_render_update_names_the_address_and_queue_only_when_needed() -> None:
    payload = update_payload(None, LIGHT_ALL_DAY)

    def title(**counts: int) -> str:
        return render_update(payload | counts, NOW).splitlines()[0]

    assert title(address_count=1, queue_count=1) == "💡 Оновлення на сьогодні (17.10):"
    assert title(address_count=2) == "💡 Оновлення на сьогодні (17.10) · <b>Дім</b>:"
    assert title(address_count=1, queue_count=2) == "💡 Оновлення на сьогодні (17.10) · черга 4.1:"
    assert title(address_count=2, queue_count=2) == (
        "💡 Оновлення на сьогодні (17.10) · <b>Дім</b> (черга 4.1):"
    )
    # Queued before address_count existed.
    assert title() == "💡 Оновлення на сьогодні (17.10) · <b>Дім</b>:"


def test_render_update_marks_an_extended_outage_as_new() -> None:
    previous = LIGHT_ALL_DAY | {"10:00": "1"}
    payload = update_payload(previous, previous | {"10:30": "1"})

    assert "🔴 10:00–11:00 немає світла 🆕" in render_update(payload, NOW).splitlines()


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
            "🪫 За 15 хв можуть ВИМКНУТИ світло (з 10:00, точно – о 10:30) · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(latest="2026-10-17T07:00:00+00:00"),
            False,
            "🪫 За 15 хв ВИМКНУТЬ світло (о 10:00) · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(latest=None),
            False,
            "🪫 За 15 хв можливе ВИМКНЕННЯ з 10:00 · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(minutes=30),
            True,
            "🔋 За 30 хв мають ДАТИ світло (з 10:00, точно – о 10:30) · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(latest="2026-10-17T07:00:00+00:00"),
            True,
            "🔋 За 15 хв ДАДУТЬ світло (о 10:00) · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(latest=None),
            True,
            "🔋 За 15 хв можливе ПОВЕРНЕННЯ світла з 10:00 · <b>Дім &lt;&amp;&gt;</b>",
        ),
        (
            reminder_payload(queue_count=2),
            False,
            "🪫 За 15 хв можуть ВИМКНУТИ світло (з 10:00, точно – о 10:30) "
            "· <b>Дім &lt;&amp;&gt;</b> (черга 4.1)",
        ),
        (
            reminder_payload(queue_count=2, latest="2026-10-17T07:00:00+00:00"),
            True,
            "🔋 За 15 хв ДАДУТЬ світло (о 10:00) · <b>Дім &lt;&amp;&gt;</b> (черга 4.1)",
        ),
        (
            reminder_payload(address_count=1, latest="2026-10-17T07:00:00+00:00"),
            False,
            "🪫 За 15 хв ВИМКНУТЬ світло (о 10:00)",
        ),
        (
            reminder_payload(address_count=1, queue_count=2),
            True,
            "🔋 За 15 хв мають ДАТИ світло (з 10:00, точно – о 10:30) · черга 4.1",
        ),
        (
            reminder_payload(address_count=1, latest="2026-10-17T08:30:00+00:00"),
            False,
            "🪫 За 15 хв можуть ВИМКНУТИ світло (з 10:00, точно – об 11:30)",
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
            "Перевір, чи все гаразд, у «⚙️ Налаштування».",
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
            "Пуші про оновлення графіка і планові роботи: вимкнено",
            "🪫 Нагадати перед вимкненням: 15 хв",
            "🔋 Нагадати перед поверненням світла: без",
            "⏱ Нагадувати до: можливого відключення 🟡",
        ]
    )
    assert render_settings(replace(subscription, remind_exact=True)).endswith(
        "⏱ Нагадувати до: точного відключення 🔴"
    )


def test_volyn_settings_have_no_reminder_mode_since_it_has_no_switching() -> None:
    volyn = replace(SUBSCRIPTION, subqueues=("voe:6.1",), tracked_subqueues=("voe:6.1",))

    assert "⏱" not in render_settings(volyn)


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
        "🛠 <b>Дім</b>: планові роботи 22.08 з 08:30 до 17:30 – Ремонт ПЛ"
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


def test_status_lists_lviv_after_the_other_regions() -> None:
    report = StatusReport(
        version="0.1.0",
        users=1,
        subscriptions=2,
        pending_messages=0,
        subqueues=(
            SubqueueStatus("loe:3.1", NOW - timedelta(minutes=5), date(2026, 10, 17)),
            SubqueueStatus("4.1", NOW - timedelta(minutes=5), None),
        ),
        stale_after=timedelta(minutes=15),
    )

    assert render_status(report, NOW).endswith(
        "\n<b>Тернопільська</b>\n"
        "4.1: опитано 17.10 17:15, графіків ще немає\n"
        "\n<b>Львівська</b>\n"
        "3.1: опитано 17.10 17:15, останній графік на 17.10"
    )


def test_status_separates_the_last_poll_from_the_last_schedule() -> None:
    report = StatusReport(
        version="0.1.0",
        users=2,
        subscriptions=3,
        pending_messages=1,
        subqueues=(
            SubqueueStatus("voe:1.2", NOW - timedelta(minutes=5), None),
            SubqueueStatus("4.1#7", NOW - timedelta(minutes=5), date(2026, 10, 15)),
            SubqueueStatus("2.2#1", NOW - timedelta(minutes=16), None),
            SubqueueStatus("1.1", None, None),
        ),
        stale_after=timedelta(minutes=15),
    )

    assert render_status(report, NOW) == (
        "📊 <b>Лямпочка 0.1.0</b>\n"
        "Користувачів: 2, адрес: 3, у черзі розсилки: 1\n"
        "\n<b>Тернопільська</b>\n"
        "4.1: опитано 17.10 17:15, останній графік на 15.10\n"
        "⚠️ 2.2: опитано 17.10 17:04, графіків ще немає\n"
        "⚠️ 1.1: ще не опитувалась\n"
        "\n<b>Волинська</b>\n"
        "1.2: опитано 17.10 17:15, графіків ще немає"
    )


def test_status_stale_threshold_comes_from_the_report() -> None:
    report = StatusReport(
        version="0.1.0",
        users=1,
        subscriptions=1,
        pending_messages=0,
        subqueues=(SubqueueStatus("4.1", NOW - timedelta(minutes=16), None),),
        stale_after=timedelta(minutes=20),
    )

    assert "⚠️" not in render_status(report, NOW)


def test_a_lviv_address_points_to_lvivoblenergo() -> None:
    lviv = replace(SUBSCRIPTION, subqueues=("loe:3.1",), tracked_subqueues=("loe:3.1",))

    text = render_day(lviv, [], TOMORROW, NOW)

    assert "poweron.loe.lviv.ua" in text
    assert "toe.com.ua" not in text


def test_lviv_settings_have_no_reminder_mode_since_it_has_no_switching() -> None:
    lviv = replace(SUBSCRIPTION, subqueues=("loe:3.1",), tracked_subqueues=("loe:3.1",))

    assert "⏱" not in render_settings(lviv)


def test_a_volyn_address_points_to_volynoblenergo_not_ternopil() -> None:
    volyn = replace(SUBSCRIPTION, subqueues=("voe:6.1",), tracked_subqueues=("voe:6.1",))
    slots = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    update = update_payload(None, slots | {"23:00": "1"}) | {"cherg_gpv": "voe:6.1"}
    gone = {"label": "Дім", "previous": ["voe:6.1"], "current": [], "tracked": ["voe:6.1"]}

    for text in (
        render_day(volyn, [], TOMORROW, NOW),
        render_update(update, NOW),
        render_subqueues_changed(gone),
    ):
        assert "energy.volyn.ua" in text
        assert "toe.com.ua" not in text


def test_render_update_withdraws_a_reminder_it_made_stale() -> None:
    off = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    payload = update_payload(off | {"17:30": "1"}, off)

    text = render_update(payload | {"stale_reminders": ["2026-10-17T14:30:00+00:00"]}, NOW)

    assert text.splitlines()[2] == "⚠️ Нагадування про вимкнення о 17:30 уже неактуальне."
    assert "⚠️" not in render_update(payload, NOW)


def test_render_update_says_ob_before_eleven_oclock() -> None:
    off = {f"{hour:02d}:{minute:02d}": "0" for hour in range(24) for minute in (0, 30)}
    payload = update_payload(off | {"11:00": "1"}, off)
    stale = ["2026-10-17T08:00:00+00:00", "2026-10-17T10:00:00+00:00"]

    text = render_update(payload | {"stale_reminders": stale}, NOW)

    assert text.splitlines()[2] == "⚠️ Нагадування про вимкнення об 11:00, 13:00 уже неактуальне."


def emergency(ends_at: datetime, reason: str = "") -> PlannedWork:
    return PlannedWork(1, 1, ends_at - timedelta(hours=3), ends_at, reason, ("5",))


EVENING = datetime(2026, 11, 25, 20, 0, tzinfo=KYIV)


def test_emergency_outage_ending_today_shows_the_time() -> None:
    text = render_emergency(emergency(datetime(2026, 11, 25, 22, 30, tzinfo=KYIV)), EVENING)

    assert text == "⚠️ <b>Зараз аварійне відключення</b>, світло обіцяють дати о 22:30"


def test_emergency_outage_ending_on_another_day_shows_the_date() -> None:
    ends_at = datetime(2026, 11, 26, 11, 0, tzinfo=KYIV)

    text = render_emergency(emergency(ends_at, "Пошкодження <КЛ>"), EVENING)

    assert text == (
        "⚠️ <b>Зараз аварійне відключення</b>, світло обіцяють дати 26.11 об 11:00\n"
        "Причина: Пошкодження &lt;КЛ&gt;"
    )

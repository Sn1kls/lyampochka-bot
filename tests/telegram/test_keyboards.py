from dataclasses import replace

from aiogram.types import InlineKeyboardMarkup

from poweron.adapters.telegram.keyboards import (
    Decision,
    Page,
    Pick,
    SettingChange,
    SubscriptionChoice,
    actions_keyboard,
    choice_keyboard,
    day_keyboard,
    menu_keyboard,
    remove_confirm_keyboard,
    settings_keyboard,
)
from tests.telegram.test_render import SUBSCRIPTION

LABELS = [f"Item {number}" for number in range(20)]


def texts_of(markup: InlineKeyboardMarkup) -> list[list[str]]:
    return [[button.text for button in row] for row in markup.inline_keyboard]


def test_first_page_has_eight_items_and_only_next() -> None:
    markup = choice_keyboard("city", LABELS, generation=4)

    assert [row[0] for row in texts_of(markup)[:8]] == LABELS[:8]
    assert texts_of(markup)[8:] == [["▶️"], ["Скасувати"]]
    assert Page.unpack(markup.inline_keyboard[8][0].callback_data or "") == Page(
        kind="city", number=1, generation=4
    )


def test_middle_page_has_both_arrows_and_absolute_item_indexes() -> None:
    markup = choice_keyboard("street", LABELS, generation=4, page=1)

    assert texts_of(markup)[8] == ["◀️", "▶️"]
    first_pick = Pick.unpack(markup.inline_keyboard[0][0].callback_data or "")
    assert first_pick == Pick(kind="street", index=8, generation=4)


def test_last_page_has_only_previous() -> None:
    markup = choice_keyboard("street", LABELS, generation=4, page=2)

    assert [row[0] for row in texts_of(markup)[:4]] == LABELS[16:]
    assert texts_of(markup)[4:] == [["◀️"], ["Скасувати"]]


def test_short_list_has_no_navigation_and_cancel_declines_the_wizard() -> None:
    markup = choice_keyboard("city", LABELS[:3], generation=4)

    assert texts_of(markup) == [[label] for label in LABELS[:3]] + [["Скасувати"]]
    cancel = Decision.unpack(markup.inline_keyboard[-1][0].callback_data or "")
    assert cancel == Decision(action="add", accepted=False)


def test_buildings_are_a_grid_of_four_with_twenty_per_page() -> None:
    numbers = [str(number) for number in range(1, 46)]

    rows = texts_of(choice_keyboard("building", numbers, generation=4))

    assert rows[:5] == [numbers[start : start + 4] for start in range(0, 20, 4)]
    assert rows[5:] == [["▶️"], ["Скасувати"]]


def test_settings_are_labelled_buttons_that_cycle_their_values() -> None:
    subscription = replace(
        SUBSCRIPTION, notify_on_update=True, remind_before_off_min=30, remind_before_on_min=0
    )

    markup = settings_keyboard(subscription)

    assert texts_of(markup) == [
        ["✅ Пуші про оновлення"],
        ["🪫 Нагадати до вимкнення: 30 хв"],
        ["🔋 Нагадати до повернення: без"],
        ["⏱ Нагадувати до: можливого 🟡"],
        ["✏️ Змінити назву"],
    ]
    *setting_rows, rename_row = markup.inline_keyboard
    presses = [SettingChange.unpack(row[0].callback_data or "") for row in setting_rows]
    assert [(press.field, press.value) for press in presses] == [
        ("notify_on_update", 0),
        ("remind_before_off_min", 60),
        ("remind_before_on_min", 15),
        ("remind_exact", 1),
    ]
    assert SubscriptionChoice.unpack(rename_row[0].callback_data or "") == SubscriptionChoice(
        action="rename", subscription_id=SUBSCRIPTION.id
    )
    exact = settings_keyboard(replace(subscription, remind_exact=True))
    assert texts_of(exact)[-2] == ["⏱ Нагадувати до: точного 🔴"]
    assert SettingChange.unpack(exact.inline_keyboard[-2][0].callback_data or "").value == 0


def test_volyn_settings_have_no_reminder_mode_button() -> None:
    volyn = replace(SUBSCRIPTION, subqueues=("voe:6.1",), tracked_subqueues=("voe:6.1",))

    assert ["⏱ Нагадувати до: можливого 🟡"] not in texts_of(settings_keyboard(volyn))


def test_the_longest_reminder_wraps_around_to_none() -> None:
    markup = settings_keyboard(replace(SUBSCRIPTION, remind_before_off_min=60))

    press = SettingChange.unpack(markup.inline_keyboard[1][0].callback_data or "")
    assert press.value == 0


def styles_of(markup: InlineKeyboardMarkup) -> list[list[str | None]]:
    return [[button.style for button in row] for row in markup.inline_keyboard]


def test_settings_paint_what_is_on_green_and_leave_what_is_off_plain() -> None:
    subscription = replace(
        SUBSCRIPTION,
        subqueues=("2.2", "4.1#7"),
        tracked_subqueues=("4.1#7",),
        notify_on_update=False,
    )

    assert styles_of(settings_keyboard(subscription)) == [
        [None],
        ["success"],
        [None],
        [None],
        [None],
        [None],
        [None],
    ]
    assert styles_of(settings_keyboard(replace(subscription, notify_on_update=True)))[2] == [
        "success"
    ]


def test_removing_is_red_and_today_is_the_highlighted_day() -> None:
    assert styles_of(actions_keyboard("add", "remove")) == [[None], ["danger"]]
    assert styles_of(remove_confirm_keyboard(1)) == [["danger", None]]
    assert styles_of(day_keyboard(SUBSCRIPTION)) == [["primary", None]]


def test_the_schedule_is_the_highlighted_menu_button() -> None:
    styles = [[button.style for button in row] for row in menu_keyboard().keyboard]

    assert styles == [["primary", None], [None, None], [None, None]]

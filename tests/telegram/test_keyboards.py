from dataclasses import replace

from aiogram.types import InlineKeyboardMarkup

from poweron.adapters.telegram.keyboards import (
    Decision,
    Page,
    Pick,
    SettingChange,
    choice_keyboard,
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


def test_settings_are_three_labelled_buttons_that_cycle_the_minutes() -> None:
    subscription = replace(
        SUBSCRIPTION, notify_on_update=True, remind_before_off_min=30, remind_before_on_min=0
    )

    markup = settings_keyboard(subscription)

    assert texts_of(markup) == [
        ["✅ Пуші про оновлення"],
        ["⏰ Нагадати до вимкнення: 30 хв"],
        ["💡 Нагадати до повернення: без"],
    ]
    presses = [SettingChange.unpack(row[0].callback_data or "") for row in markup.inline_keyboard]
    assert [(press.field, press.value) for press in presses] == [
        ("notify_on_update", 0),
        ("remind_before_off_min", 60),
        ("remind_before_on_min", 15),
    ]


def test_the_longest_reminder_wraps_around_to_none() -> None:
    markup = settings_keyboard(replace(SUBSCRIPTION, remind_before_off_min=60))

    press = SettingChange.unpack(markup.inline_keyboard[1][0].callback_data or "")
    assert press.value == 0

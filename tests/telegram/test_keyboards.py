from aiogram.types import InlineKeyboardMarkup

from poweron.adapters.telegram.keyboards import Decision, Page, Pick, choice_keyboard

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
    markup = choice_keyboard("building", LABELS, generation=4, page=2)

    assert [row[0] for row in texts_of(markup)[:4]] == LABELS[16:]
    assert texts_of(markup)[4:] == [["◀️"], ["Скасувати"]]


def test_short_list_has_no_navigation_and_cancel_declines_the_wizard() -> None:
    markup = choice_keyboard("city", LABELS[:3], generation=4)

    assert texts_of(markup) == [[label] for label in LABELS[:3]] + [["Скасувати"]]
    cancel = Decision.unpack(markup.inline_keyboard[-1][0].callback_data or "")
    assert cancel == Decision(action="add", accepted=False)

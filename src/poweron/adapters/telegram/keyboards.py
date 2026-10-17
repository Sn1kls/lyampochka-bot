from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from poweron.core.domain.models import Subscription

from . import texts

PAGE_SIZE = 8
BUILDING_COLUMNS = 4
BUILDING_PAGE_SIZE = 20


class Page(CallbackData, prefix="pg"):
    kind: str
    number: int
    generation: int


class Pick(CallbackData, prefix="pk"):
    kind: str
    index: int
    generation: int


class DayChoice(CallbackData, prefix="day"):
    subscription_id: int
    offset: int


class SubscriptionChoice(CallbackData, prefix="sub"):
    action: str
    subscription_id: int


class Decision(CallbackData, prefix="ok"):
    action: str
    accepted: bool


def choice_keyboard(
    kind: str, labels: Sequence[str], generation: int, page: int = 0
) -> InlineKeyboardMarkup:
    """`generation` ties the buttons to one search, so buttons of an older list are detectable."""
    columns, page_size = (
        (BUILDING_COLUMNS, BUILDING_PAGE_SIZE) if kind == "building" else (1, PAGE_SIZE)
    )
    start = page * page_size
    builder = InlineKeyboardBuilder()
    for index, label in enumerate(labels[start : start + page_size], start):
        builder.button(
            text=label, callback_data=Pick(kind=kind, index=index, generation=generation)
        )
    builder.adjust(columns)
    navigation = InlineKeyboardBuilder()
    if page > 0:
        navigation.button(
            text=texts.BUTTON_PREVIOUS,
            callback_data=Page(kind=kind, number=page - 1, generation=generation),
        )
    if start + page_size < len(labels):
        navigation.button(
            text=texts.BUTTON_NEXT,
            callback_data=Page(kind=kind, number=page + 1, generation=generation),
        )
    cancel = InlineKeyboardBuilder()
    cancel.button(text=texts.BUTTON_CANCEL, callback_data=Decision(action="add", accepted=False))
    builder.attach(navigation)
    builder.attach(cancel)
    return builder.as_markup()


def day_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for text, offset in ((texts.TODAY, 0), (texts.TOMORROW, 1)):
        builder.button(
            text=text, callback_data=DayChoice(subscription_id=subscription_id, offset=offset)
        )
    return builder.as_markup()


def subscription_keyboard(
    action: str, subscriptions: Sequence[Subscription]
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subscription in subscriptions:
        builder.button(
            text=subscription.label,
            callback_data=SubscriptionChoice(action=action, subscription_id=subscription.id),
        )
    builder.adjust(1)
    return builder.as_markup()


def confirm_keyboard(action: str, accept_text: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=accept_text, callback_data=Decision(action=action, accepted=True))
    builder.button(text=texts.BUTTON_CANCEL, callback_data=Decision(action=action, accepted=False))
    return builder.as_markup()

from collections.abc import Sequence

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from poweron.core.domain.models import Subscription

from . import texts

PAGE_SIZE = 8


class Page(CallbackData, prefix="pg"):
    kind: str
    number: int


class Pick(CallbackData, prefix="pk"):
    kind: str
    index: int


class DayChoice(CallbackData, prefix="day"):
    subscription_id: int
    offset: int


class SubscriptionChoice(CallbackData, prefix="sub"):
    action: str
    subscription_id: int


class Decision(CallbackData, prefix="ok"):
    action: str
    accepted: bool


def choice_keyboard(kind: str, labels: Sequence[str], page: int = 0) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    rows = [
        [InlineKeyboardButton(text=label, callback_data=Pick(kind=kind, index=index).pack())]
        for index, label in enumerate(labels[start : start + PAGE_SIZE], start)
    ]
    navigation = []
    if page > 0:
        navigation.append(_page_button("◀️", kind, page - 1))
    if start + PAGE_SIZE < len(labels):
        navigation.append(_page_button("▶️", kind, page + 1))
    if navigation:
        rows.append(navigation)
    rows.append([_decision_button(texts.BUTTON_CANCEL, "add", accepted=False)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=DayChoice(subscription_id=subscription_id, offset=offset).pack(),
                )
                for text, offset in ((texts.TODAY, 0), (texts.TOMORROW, 1))
            ]
        ]
    )


def subscription_keyboard(
    action: str, subscriptions: Sequence[Subscription]
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=subscription.label,
                    callback_data=SubscriptionChoice(
                        action=action, subscription_id=subscription.id
                    ).pack(),
                )
            ]
            for subscription in subscriptions
        ]
    )


def confirm_keyboard(action: str, accept_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _decision_button(accept_text, action, accepted=True),
                _decision_button(texts.BUTTON_CANCEL, action, accepted=False),
            ]
        ]
    )


def _page_button(text: str, kind: str, number: int) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=Page(kind=kind, number=number).pack())


def _decision_button(text: str, action: str, accepted: bool) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text=text, callback_data=Decision(action=action, accepted=accepted).pack()
    )

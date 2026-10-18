from collections.abc import Sequence
from typing import Literal

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from poweron.core.domain.models import Subscription
from poweron.core.services.subscriptions import REMINDER_MINUTES

from . import texts
from .render import minutes_text

PAGE_SIZE = 8
SETTING_VALUES = {
    "notify_on_update": (0, 1),
    "remind_before_off_min": REMINDER_MINUTES,
    "remind_before_on_min": REMINDER_MINUTES,
}
BUILDING_COLUMNS = 4
BUILDING_PAGE_SIZE = 20
MENU_ROWS = (
    (texts.MENU_SCHEDULE, texts.MENU_NEXT),
    (texts.MENU_LIST, texts.MENU_SETTINGS),
)
# Older clients may still show the previous seven-button keyboard, so its labels keep working.
MENU_LABELS = frozenset(label for row in MENU_ROWS for label in row) | {
    texts.MENU_ADD,
    texts.MENU_REMOVE,
    texts.MENU_HELP,
}
ActionName = Literal["add", "remove"]
ACTION_LABELS: dict[ActionName, str] = {"add": texts.MENU_ADD, "remove": texts.MENU_REMOVE}


class Page(CallbackData, prefix="pg"):
    kind: str
    number: int
    generation: int


class Pick(CallbackData, prefix="pk"):
    kind: str
    index: int
    generation: int


class DayChoice(CallbackData, prefix="day"):
    """`subqueue` empty means the tracked queues."""

    subscription_id: int
    offset: int
    subqueue: str = ""


class QueueChoice(CallbackData, prefix="q"):
    """`index` -1 means all queues of the building."""

    index: int
    generation: int


class SubscriptionChoice(CallbackData, prefix="sub"):
    action: str
    subscription_id: int


class SettingChange(CallbackData, prefix="set"):
    """`field` is a `Subscriptions.update_settings` parameter; `value` is 0/1 for the push toggle."""

    subscription_id: int
    field: str
    value: int


class Action(CallbackData, prefix="go"):
    """An inline shortcut to what a menu button or command does."""

    name: ActionName


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


def actions_keyboard(*names: ActionName) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for name in names:
        builder.button(text=ACTION_LABELS[name], callback_data=Action(name=name))
    builder.adjust(1)
    return builder.as_markup()


def menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in MENU_ROWS],
        resize_keyboard=True,
        is_persistent=True,
    )


def queue_keyboard(subqueues: Sequence[str], generation: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, queue in enumerate(subqueues):
        builder.button(
            text=texts.BUTTON_QUEUE.format(queue=_plain_label(queue)),
            callback_data=QueueChoice(index=index, generation=generation),
        )
    builder.button(
        text=texts.BUTTON_ALL_QUEUES, callback_data=QueueChoice(index=-1, generation=generation)
    )
    builder.button(text=texts.BUTTON_CANCEL, callback_data=Decision(action="add", accepted=False))
    builder.adjust(1)
    return builder.as_markup()


def day_keyboard(
    subscription: Subscription, shown_offset: int | None = None, shown_subqueue: str = ""
) -> InlineKeyboardMarkup:
    """After a day is shown, the building's untracked queues get buttons for that same day."""
    builder = InlineKeyboardBuilder()
    for text, offset in ((texts.TODAY, 0), (texts.TOMORROW, 1)):
        builder.button(
            text=text, callback_data=DayChoice(subscription_id=subscription.id, offset=offset)
        )
    if shown_offset is not None:
        for queue in subscription.subqueues:
            if queue not in subscription.tracked_subqueues and queue != shown_subqueue:
                builder.row(
                    InlineKeyboardButton(
                        text=texts.BUTTON_QUEUE.format(queue=_plain_label(queue)),
                        callback_data=DayChoice(
                            subscription_id=subscription.id, offset=shown_offset, subqueue=queue
                        ).pack(),
                    )
                )
    return builder.as_markup()


def _plain_label(cherg_gpv: str) -> str:
    return cherg_gpv.split("#")[0]


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


def settings_keyboard(subscription: Subscription) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = (
        texts.BUTTON_UPDATES_ON if subscription.notify_on_update else texts.BUTTON_UPDATES_OFF
    )
    builder.button(
        text=toggle_text,
        callback_data=SettingChange(
            subscription_id=subscription.id,
            field="notify_on_update",
            value=int(not subscription.notify_on_update),
        ),
    )
    for field, current, template in (
        ("remind_before_off_min", subscription.remind_before_off_min, texts.BUTTON_REMINDER_OFF),
        ("remind_before_on_min", subscription.remind_before_on_min, texts.BUTTON_REMINDER_ON),
    ):
        builder.button(
            text=template.format(value=minutes_text(current)),
            callback_data=SettingChange(
                subscription_id=subscription.id, field=field, value=_next_minutes(current)
            ),
        )
    builder.adjust(1)
    return builder.as_markup()


def _next_minutes(current: int) -> int:
    """Each press moves to the next option and wraps around after the last."""
    if current not in REMINDER_MINUTES:
        return REMINDER_MINUTES[0]
    return REMINDER_MINUTES[(REMINDER_MINUTES.index(current) + 1) % len(REMINDER_MINUTES)]

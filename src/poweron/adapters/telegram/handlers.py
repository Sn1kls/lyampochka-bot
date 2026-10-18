from collections.abc import Awaitable, Callable, Sequence
from contextlib import suppress
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Any

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, ExceptionTypeFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    TelegramObject,
    User,
)

from poweron.core.domain.models import KYIV, Building, City, Street, Subscription
from poweron.core.ports import SourceError
from poweron.core.services.catalog import Catalog, find_by_name
from poweron.core.services.schedules import Schedules
from poweron.core.services.status import Status
from poweron.core.services.subscriptions import Subscriptions

from . import keyboards, texts
from .middleware import KnownUser
from .render import (
    render_confirm,
    render_day,
    render_list,
    render_next,
    render_no_schedule_for_address,
    render_settings,
    render_status,
    subqueue_label,
)

router = Router(name="telegram")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
router.message.outer_middleware(KnownUser())
router.callback_query.outer_middleware(KnownUser())

NOT_MODIFIED = "message is not modified"


class AddFlow(StatesGroup):
    city = State()
    street = State()
    building = State()
    queues = State()
    confirm = State()


def _now() -> datetime:
    return datetime.now(UTC)


async def _show_settings(target: Message | CallbackQuery, subscription: Subscription) -> None:
    await _respond(target, render_settings(subscription), keyboards.settings_keyboard(subscription))


async def _respond(
    event: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)
        return
    await event.answer()  # stop the button spinner before the slower edit
    if isinstance(event.message, Message):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as error:
            # the same button pressed twice edits to identical text
            if NOT_MODIFIED not in error.message:
                raise


async def _reset(state: FSMContext) -> None:
    """Leaves the wizard but keeps its search counter, so buttons of a finished wizard stay stale."""
    generation = (await state.get_data()).get("generation", 0)
    await state.set_data({"generation": generation})
    await state.set_state(None)


async def leave_wizard_on_menu_button(
    handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
    event: TelegramObject,
    data: dict[str, Any],
) -> Any:
    if isinstance(event, Message) and event.text in keyboards.MENU_LABELS:
        await _reset(data["state"])
    return await handler(event, data)


router.message.outer_middleware(leave_wizard_on_menu_button)


async def _finish(
    callback: CallbackQuery, text: str, keyboard: ReplyKeyboardMarkup | ReplyKeyboardRemove
) -> None:
    """A reply keyboard can only come with a new message, so the inline one is closed instead."""
    await callback.answer()
    if isinstance(callback.message, Message):
        with suppress(TelegramBadRequest):
            await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(text, reply_markup=keyboard)


@router.errors(ExceptionTypeFilter(SourceError))
async def on_source_error(event: ErrorEvent) -> None:
    update = event.update
    if update.message is not None:
        await update.message.answer(texts.SOURCE_DOWN)
    elif update.callback_query is not None:
        await update.callback_query.answer(texts.SOURCE_DOWN, show_alert=True)


@router.message(Command("start"))
async def start(
    message: Message, event_from_user: User, state: FSMContext, subscriptions: Subscriptions
) -> None:
    await _reset(state)
    await subscriptions.register(
        "telegram",
        str(event_from_user.id),
        "telegram",
        str(message.chat.id),
        display_name(event_from_user),
    )
    await message.answer(texts.GREETING, reply_markup=keyboards.menu_keyboard())


def display_name(user: User) -> str:
    return f"{user.full_name} @{user.username}" if user.username else user.full_name


@router.message(Command("help"))
@router.message(F.text == texts.MENU_HELP)
async def help_(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("list"))
@router.message(F.text == texts.MENU_LIST)
async def list_(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    items = await subscriptions.of_user(user_id)
    await message.answer(render_list(items) if items else texts.NO_SUBSCRIPTIONS)


@router.message(Command("schedule"))
@router.message(F.text == texts.MENU_SCHEDULE)
async def schedule(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    async def ask_day(subscription: Subscription) -> None:
        await message.answer(texts.CHOOSE_DAY, reply_markup=keyboards.day_keyboard(subscription))

    await _choose_subscription(message, user_id, subscriptions, "schedule", ask_day)


@router.message(Command("next"))
@router.message(F.text == texts.MENU_NEXT)
async def next_(
    message: Message, user_id: int, subscriptions: Subscriptions, schedules: Schedules
) -> None:
    async def answer_next(subscription: Subscription) -> None:
        await message.answer(await _next_text(schedules, subscription))

    await _choose_subscription(message, user_id, subscriptions, "next", answer_next)


@router.message(Command("remove"))
@router.message(F.text == texts.MENU_REMOVE)
async def remove(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    await _choose_subscription(
        message, user_id, subscriptions, "remove", prompt=texts.REMOVE_PROMPT
    )


@router.message(Command("settings"))
@router.message(F.text == texts.MENU_SETTINGS)
async def settings(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    async def show_settings(subscription: Subscription) -> None:
        await _show_settings(message, subscription)

    await _choose_subscription(message, user_id, subscriptions, "settings", show_settings)


@router.message(Command("status"))
async def show_status(message: Message, status: Status | None, admin_chat_id: int | None) -> None:
    if status is None or message.chat.id != admin_chat_id:
        return
    await message.answer(render_status(await status.report(), _now()))


@router.message(Command("forget"))
async def forget(message: Message) -> None:
    await message.answer(
        texts.FORGET_CONFIRM,
        reply_markup=keyboards.confirm_keyboard("forget", texts.BUTTON_FORGET),
    )


async def _choose_subscription(
    message: Message,
    user_id: int,
    subscriptions: Subscriptions,
    action: str,
    on_single: Callable[[Subscription], Awaitable[None]] | None = None,
    prompt: str = texts.CHOOSE_SUBSCRIPTION,
) -> None:
    """Handles none / exactly one / several addresses; `on_single` None means always ask."""
    items = await subscriptions.of_user(user_id)
    if not items:
        await message.answer(texts.NO_SUBSCRIPTIONS)
    elif len(items) == 1 and on_single is not None:
        await on_single(items[0])
    else:
        await message.answer(prompt, reply_markup=keyboards.subscription_keyboard(action, items))


async def _next_text(schedules: Schedules, subscription: Subscription) -> str:
    now = _now()
    return render_next(subscription, await schedules.next_event(subscription, now), now)


@router.callback_query(keyboards.SubscriptionChoice.filter())
async def choose_subscription(
    callback: CallbackQuery,
    callback_data: keyboards.SubscriptionChoice,
    user_id: int,
    subscriptions: Subscriptions,
    schedules: Schedules,
) -> None:
    subscription = await subscriptions.get(user_id, callback_data.subscription_id)
    if subscription is None:
        await _respond(callback, texts.ADDRESS_GONE)
    elif callback_data.action == "schedule":
        await _respond(callback, texts.CHOOSE_DAY, keyboards.day_keyboard(subscription))
    elif callback_data.action == "next":
        await _respond(callback, await _next_text(schedules, subscription))
    elif callback_data.action == "settings":
        await _show_settings(callback, subscription)
    elif callback_data.action == "remove":
        removed = await subscriptions.remove(user_id, subscription.id)
        if removed:
            await _finish(callback, texts.REMOVED, keyboards.menu_keyboard())
        else:
            await _respond(callback, texts.ADDRESS_GONE)


@router.callback_query(keyboards.SettingChange.filter())
async def change_setting(
    callback: CallbackQuery,
    callback_data: keyboards.SettingChange,
    user_id: int,
    subscriptions: Subscriptions,
) -> None:
    if callback_data.value not in keyboards.SETTING_VALUES.get(callback_data.field, ()):
        await callback.answer(texts.STALE_BUTTON, show_alert=True)
        return
    changes: dict[str, Any] = {
        callback_data.field: bool(callback_data.value)
        if callback_data.field == "notify_on_update"
        else callback_data.value
    }
    subscription = await subscriptions.update_settings(
        user_id, callback_data.subscription_id, **changes
    )
    if subscription is None:
        await _respond(callback, texts.ADDRESS_GONE)
    else:
        await _show_settings(callback, subscription)


@router.callback_query(keyboards.DayChoice.filter())
async def show_day(
    callback: CallbackQuery,
    callback_data: keyboards.DayChoice,
    user_id: int,
    subscriptions: Subscriptions,
    schedules: Schedules,
) -> None:
    subscription = await subscriptions.get(user_id, callback_data.subscription_id)
    if subscription is None:
        await _respond(callback, texts.ADDRESS_GONE)
        return
    now = _now()
    day = now.astimezone(KYIV).date() + timedelta(days=callback_data.offset)
    viewed = _viewed_queues(subscription, callback_data.subqueue)
    views = await schedules.day(subscription, day, viewed[0] if viewed else None)
    await _respond(
        callback,
        render_day(subscription, views, day, now, viewed),
        keyboards.day_keyboard(subscription, callback_data.offset, callback_data.subqueue),
    )


@router.callback_query(keyboards.Decision.filter(F.action == "forget"))
async def decide_forget(
    callback: CallbackQuery,
    callback_data: keyboards.Decision,
    state: FSMContext,
    user_id: int,
    subscriptions: Subscriptions,
) -> None:
    if callback_data.accepted:
        await subscriptions.forget(user_id)
        await _reset(state)
        await _finish(callback, texts.FORGOTTEN, ReplyKeyboardRemove())
    else:
        await _finish(callback, texts.CANCELLED, keyboards.menu_keyboard())


@router.message(Command("add"))
@router.message(F.text == texts.MENU_ADD)
async def add(message: Message, state: FSMContext) -> None:
    await _reset(state)
    await state.set_state(AddFlow.city)
    await message.answer(texts.ASK_CITY)


@router.callback_query(keyboards.Decision.filter((F.action == "add") & ~F.accepted))
async def cancel_add(callback: CallbackQuery, state: FSMContext) -> None:
    await _reset(state)
    await _respond(callback, texts.CANCELLED)


@router.callback_query(AddFlow.city, keyboards.Page.filter(F.kind == "city"))
@router.callback_query(AddFlow.street, keyboards.Page.filter(F.kind == "street"))
@router.callback_query(AddFlow.building, keyboards.Page.filter(F.kind == "building"))
async def turn_page(
    callback: CallbackQuery, callback_data: keyboards.Page, state: FSMContext
) -> None:
    data = await _current_data(callback, callback_data, state)
    if data is None:
        return
    await callback.answer()  # stop the button spinner before the slower edit
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.choice_keyboard(
                callback_data.kind, data["labels"], data["generation"], callback_data.number
            )
        )


async def _current_data(
    callback: CallbackQuery,
    callback_data: keyboards.Page | keyboards.Pick | keyboards.QueueChoice,
    state: FSMContext,
) -> dict[str, Any] | None:
    """The wizard data, unless the button belongs to an older search (then the user is told)."""
    data = await state.get_data()
    if callback_data.generation != data.get("generation"):
        await callback.answer(texts.STALE_BUTTON, show_alert=True)
        return None
    return data


async def _picked_option(
    callback: CallbackQuery, callback_data: keyboards.Pick, state: FSMContext
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    data = await _current_data(callback, callback_data, state)
    if data is None:
        return None
    if not 0 <= callback_data.index < len(data["options"]):
        await callback.answer(texts.STALE_BUTTON, show_alert=True)
        return None
    return data, data["options"][callback_data.index]


async def _offer(
    event: Message | CallbackQuery,
    state: FSMContext,
    kind: str,
    items: Sequence[City | Street | Building],
    prompt: str,
) -> None:
    labels = [_choice_label(item) for item in items]
    generation = (await state.get_data()).get("generation", 0) + 1
    await state.update_data(
        options=[asdict(item) for item in items], labels=labels, generation=generation
    )
    await _respond(event, prompt, keyboards.choice_keyboard(kind, labels, generation))


def _choice_label(item: City | Street | Building) -> str:
    if isinstance(item, City) and item.otg_name:
        return f"{item.name} ({item.otg_name})"
    return item.name


@router.message(AddFlow.city, F.text)
async def search_city(message: Message, state: FSMContext, catalog: Catalog) -> None:
    cities = await catalog.find_cities(message.text or "", _now())
    exact = find_by_name(cities, message.text or "")
    if exact is not None:
        await _choose_city(message, state, asdict(exact))
    elif cities:
        await _offer(message, state, "city", cities, texts.CHOOSE_CITY)
    else:
        await message.answer(texts.NOTHING_FOUND)


@router.callback_query(AddFlow.city, keyboards.Pick.filter(F.kind == "city"))
async def pick_city(
    callback: CallbackQuery, callback_data: keyboards.Pick, state: FSMContext
) -> None:
    picked = await _picked_option(callback, callback_data, state)
    if picked is None:
        return
    _, city = picked
    await _choose_city(callback, state, city)


async def _choose_city(
    event: Message | CallbackQuery, state: FSMContext, city: dict[str, Any]
) -> None:
    await state.update_data(city=city)
    await state.set_state(AddFlow.street)
    await _respond(event, texts.ASK_STREET.format(city=escape(city["name"])))


@router.message(AddFlow.street, F.text)
async def search_street(message: Message, state: FSMContext, catalog: Catalog) -> None:
    city = (await state.get_data())["city"]
    streets = await catalog.find_streets(city["id"], message.text or "", _now())
    exact = find_by_name(streets, message.text or "")
    if exact is not None:
        await _choose_street(message, state, catalog, city, asdict(exact))
    elif streets:
        await _offer(message, state, "street", streets, texts.CHOOSE_STREET)
    else:
        await message.answer(texts.NOTHING_FOUND)


@router.callback_query(AddFlow.street, keyboards.Pick.filter(F.kind == "street"))
async def pick_street(
    callback: CallbackQuery,
    callback_data: keyboards.Pick,
    state: FSMContext,
    catalog: Catalog,
) -> None:
    picked = await _picked_option(callback, callback_data, state)
    if picked is None:
        return
    data, street = picked
    await _choose_street(callback, state, catalog, data["city"], street)


async def _choose_street(
    event: Message | CallbackQuery,
    state: FSMContext,
    catalog: Catalog,
    city: dict[str, Any],
    street: dict[str, Any],
) -> None:
    buildings = await catalog.buildings(city["id"], street["id"], _now())
    if not buildings:
        await _respond(event, texts.NO_BUILDINGS)
        return
    await state.update_data(street=street)
    await state.set_state(AddFlow.building)
    prompt = texts.CHOOSE_BUILDING.format(street=escape(street["name"]))
    await _offer(event, state, "building", buildings, prompt)


@router.callback_query(AddFlow.building, keyboards.Pick.filter(F.kind == "building"))
async def pick_building(
    callback: CallbackQuery, callback_data: keyboards.Pick, state: FSMContext, catalog: Catalog
) -> None:
    picked = await _picked_option(callback, callback_data, state)
    if picked is not None:
        await _choose_building(callback, state, catalog, Building(**picked[1]))


@router.message(AddFlow.building, F.text)
async def type_building(message: Message, state: FSMContext, catalog: Catalog) -> None:
    buildings = [Building(**raw) for raw in (await state.get_data())["options"]]
    building = find_by_name(buildings, message.text or "")
    if building is None:
        await message.answer(texts.BUILDING_NOT_FOUND)
        return
    await _choose_building(message, state, catalog, building)


async def _choose_building(
    event: Message | CallbackQuery, state: FSMContext, catalog: Catalog, building: Building
) -> None:
    if building.cherg_gpv is None:
        await _reject_address(event, state, building)
        return
    data = await state.get_data()
    subqueues = await catalog.subqueues(data["city"]["id"], data["street"]["id"], building)
    await state.update_data(
        building=asdict(building),
        subqueues=subqueues,
        tracked=subqueues,
        label=texts.DEFAULT_LABEL,
    )
    if len(subqueues) == 1:
        await state.set_state(AddFlow.confirm)
        await _show_confirm(event, state)
        return
    generation = data.get("generation", 0) + 1
    await state.update_data(generation=generation)
    await state.set_state(AddFlow.queues)
    queues = ", ".join(subqueue_label(queue) for queue in subqueues)
    await _respond(
        event,
        texts.CHOOSE_QUEUES.format(queues=queues),
        keyboards.queue_keyboard(subqueues, generation),
    )


@router.callback_query(AddFlow.queues, keyboards.QueueChoice.filter())
async def pick_queue(
    callback: CallbackQuery, callback_data: keyboards.QueueChoice, state: FSMContext
) -> None:
    data = await _current_data(callback, callback_data, state)
    if data is None:
        return
    if callback_data.index != -1:
        if not 0 <= callback_data.index < len(data["subqueues"]):
            await callback.answer(texts.STALE_BUTTON, show_alert=True)
            return
        await state.update_data(tracked=[data["subqueues"][callback_data.index]])
    await state.set_state(AddFlow.confirm)
    await _show_confirm(callback, state)


async def _reject_address(
    event: Message | CallbackQuery, state: FSMContext, building: Building
) -> None:
    data = await state.get_data()
    await _reset(state)
    await _respond(
        event,
        render_no_schedule_for_address(data["city"]["name"], data["street"]["name"], building.name),
    )


async def _show_confirm(event: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    text = render_confirm(
        data["city"]["name"],
        data["street"]["name"],
        data["building"]["name"],
        data["subqueues"],
        data["tracked"],
        data["label"],
    )
    await _respond(event, text, keyboards.confirm_keyboard("add", texts.BUTTON_SAVE))


@router.message(AddFlow.confirm, F.text)
async def rename(message: Message, state: FSMContext) -> None:
    label = (message.text or "").strip()[: texts.LABEL_MAX_LENGTH]
    if label:
        await state.update_data(label=label)
    await _show_confirm(message, state)


@router.callback_query(AddFlow.confirm, keyboards.Decision.filter(F.action == "add"))
async def save(
    callback: CallbackQuery, state: FSMContext, user_id: int, subscriptions: Subscriptions
) -> None:
    data = await state.get_data()
    await _reset(state)
    await subscriptions.add(
        user_id,
        data["label"],
        City(**data["city"]),
        Street(**data["street"]),
        Building(**data["building"]),
        data["subqueues"],
        data["tracked"],
        _now(),
    )
    await _finish(
        callback, texts.ADDED.format(label=escape(data["label"])), keyboards.menu_keyboard()
    )


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_BUTTON, show_alert=True)


def _viewed_queues(subscription: Subscription, subqueue: str | None) -> list[str] | None:
    return [subqueue] if subqueue and subqueue in subscription.subqueues else None


@router.message(AddFlow.queues, F.text)
async def queue_typed(message: Message) -> None:
    await message.answer(texts.PICK_QUEUE_BUTTON)

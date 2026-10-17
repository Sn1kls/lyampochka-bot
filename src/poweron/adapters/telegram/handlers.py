import contextlib
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, ExceptionTypeFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, ErrorEvent, InlineKeyboardMarkup, Message

from poweron.core.domain.models import KYIV, Building, City, Street, Subscription
from poweron.core.ports import SourceError
from poweron.core.services.catalog import Catalog, find_building
from poweron.core.services.schedules import Schedules
from poweron.core.services.subscriptions import NoScheduleForAddress, Subscriptions

from . import keyboards, texts
from .middleware import RegisterUser
from .render import render_day, render_next, subqueue_label

router = Router(name="telegram")
router.message.filter(F.chat.type == ChatType.PRIVATE)
router.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
router.message.outer_middleware(RegisterUser())
router.callback_query.outer_middleware(RegisterUser())


class AddFlow(StatesGroup):
    city = State()
    street = State()
    building = State()
    confirm = State()


def _now() -> datetime:
    return datetime.now(UTC)


async def _respond(
    event: Message | CallbackQuery, text: str, markup: InlineKeyboardMarkup | None = None
) -> None:
    if isinstance(event, Message):
        await event.answer(text, reply_markup=markup)
        return
    if isinstance(event.message, Message):
        # editing to identical text (same button pressed twice) is rejected by Telegram
        with contextlib.suppress(TelegramBadRequest):
            await event.message.edit_text(text, reply_markup=markup)
    await event.answer()


def _address(subscription: Subscription) -> str:
    return escape(
        f"{subscription.city_name}, {subscription.street_name}, "
        f"{subscription.address.building_name}"
    )


@router.errors(ExceptionTypeFilter(SourceError))
async def on_source_error(event: ErrorEvent) -> None:
    update = event.update
    if update.message is not None:
        await update.message.answer(texts.SOURCE_DOWN)
    elif update.callback_query is not None:
        await update.callback_query.answer(texts.SOURCE_DOWN, show_alert=True)


@router.message(Command("start"))
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(texts.GREETING)


@router.message(Command("help"))
async def help_(message: Message) -> None:
    await message.answer(texts.HELP)


@router.message(Command("list"))
async def list_(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    items = await subscriptions.of_user(user_id)
    if not items:
        await message.answer(texts.NO_SUBSCRIPTIONS)
        return
    lines = [
        texts.LIST_ITEM.format(
            label=escape(item.label),
            address=_address(item),
            subqueue=subqueue_label(item.cherg_gpv),
        )
        for item in items
    ]
    await message.answer("\n".join([texts.LIST_HEADER, *lines]))


@router.message(Command("schedule"))
async def schedule(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    items = await subscriptions.of_user(user_id)
    if not items:
        await message.answer(texts.NO_SUBSCRIPTIONS)
    elif len(items) == 1:
        await message.answer(texts.CHOOSE_DAY, reply_markup=keyboards.day_keyboard(items[0].id))
    else:
        await _ask_subscription(message, "schedule", items)


@router.message(Command("next"))
async def next_(
    message: Message, user_id: int, subscriptions: Subscriptions, schedules: Schedules
) -> None:
    items = await subscriptions.of_user(user_id)
    if not items:
        await message.answer(texts.NO_SUBSCRIPTIONS)
    elif len(items) == 1:
        await message.answer(await _next_text(schedules, user_id, items[0]))
    else:
        await _ask_subscription(message, "next", items)


@router.message(Command("remove"))
async def remove(message: Message, user_id: int, subscriptions: Subscriptions) -> None:
    items = await subscriptions.of_user(user_id)
    if items:
        await _ask_subscription(message, "remove", items, texts.REMOVE_PROMPT)
    else:
        await message.answer(texts.NO_SUBSCRIPTIONS)


@router.message(Command("forget"))
async def forget(message: Message) -> None:
    await message.answer(
        texts.FORGET_CONFIRM,
        reply_markup=keyboards.confirm_keyboard("forget", texts.BUTTON_FORGET),
    )


async def _ask_subscription(
    message: Message,
    action: str,
    items: Sequence[Subscription],
    prompt: str = texts.CHOOSE_SUBSCRIPTION,
) -> None:
    await message.answer(prompt, reply_markup=keyboards.subscription_keyboard(action, items))


async def _next_text(schedules: Schedules, user_id: int, subscription: Subscription) -> str:
    now = _now()
    event = await schedules.next_event(user_id, subscription.id, now)
    return render_next(subscription, event, now)


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
        await _respond(callback, texts.CHOOSE_DAY, keyboards.day_keyboard(subscription.id))
    elif callback_data.action == "next":
        await _respond(callback, await _next_text(schedules, user_id, subscription))
    elif callback_data.action == "remove":
        removed = await subscriptions.remove(user_id, subscription.id)
        await _respond(callback, texts.REMOVED if removed else texts.ADDRESS_GONE)


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
    today = datetime.now(KYIV).date()
    day = today + timedelta(days=callback_data.offset)
    view = await schedules.day(user_id, subscription.id, day)
    await _respond(
        callback,
        render_day(subscription, view, day, today),
        keyboards.day_keyboard(subscription.id),
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
        await state.clear()
    await _respond(callback, texts.FORGOTTEN if callback_data.accepted else texts.CANCELLED)


@router.message(Command("add"))
async def add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddFlow.city)
    await message.answer(texts.ASK_CITY)


@router.callback_query(keyboards.Decision.filter((F.action == "add") & ~F.accepted))
async def cancel_add(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await _respond(callback, texts.CANCELLED)


@router.callback_query(AddFlow.city, keyboards.Page.filter(F.kind == "city"))
@router.callback_query(AddFlow.street, keyboards.Page.filter(F.kind == "street"))
@router.callback_query(AddFlow.building, keyboards.Page.filter(F.kind == "building"))
async def turn_page(
    callback: CallbackQuery, callback_data: keyboards.Page, state: FSMContext
) -> None:
    labels = (await state.get_data())["labels"]
    if isinstance(callback.message, Message):
        await callback.message.edit_reply_markup(
            reply_markup=keyboards.choice_keyboard(callback_data.kind, labels, callback_data.number)
        )
    await callback.answer()


async def _offer(
    event: Message | CallbackQuery,
    state: FSMContext,
    kind: str,
    items: Sequence[City | Street | Building],
    prompt: str,
) -> None:
    labels = [_choice_label(item) for item in items]
    await state.update_data(options=[asdict(item) for item in items], labels=labels)
    await _respond(event, prompt, keyboards.choice_keyboard(kind, labels))


def _choice_label(item: City | Street | Building) -> str:
    if isinstance(item, City) and item.otg_name:
        return f"{item.name} ({item.otg_name})"
    return item.name


@router.message(AddFlow.city, F.text)
async def search_city(message: Message, state: FSMContext, catalog: Catalog) -> None:
    cities = await catalog.find_cities(message.text or "", _now())
    if cities:
        await _offer(message, state, "city", cities, texts.CHOOSE_CITY)
    else:
        await message.answer(texts.NOTHING_FOUND)


@router.callback_query(AddFlow.city, keyboards.Pick.filter(F.kind == "city"))
async def pick_city(
    callback: CallbackQuery, callback_data: keyboards.Pick, state: FSMContext
) -> None:
    city = (await state.get_data())["options"][callback_data.index]
    await state.update_data(city=city)
    await state.set_state(AddFlow.street)
    await _respond(callback, texts.ASK_STREET.format(city=escape(city["name"])))


@router.message(AddFlow.street, F.text)
async def search_street(message: Message, state: FSMContext, catalog: Catalog) -> None:
    city = (await state.get_data())["city"]
    streets = await catalog.find_streets(city["id"], message.text or "", _now())
    if streets:
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
    data = await state.get_data()
    street = data["options"][callback_data.index]
    buildings = await catalog.buildings(data["city"]["id"], street["id"], _now())
    if not buildings:
        await _respond(callback, texts.NO_BUILDINGS)
        return
    await state.update_data(street=street)
    await state.set_state(AddFlow.building)
    await _offer(callback, state, "building", buildings, texts.CHOOSE_BUILDING)


@router.callback_query(AddFlow.building, keyboards.Pick.filter(F.kind == "building"))
async def pick_building(
    callback: CallbackQuery, callback_data: keyboards.Pick, state: FSMContext
) -> None:
    raw_building = (await state.get_data())["options"][callback_data.index]
    await _choose_building(callback, state, Building(**raw_building))


@router.message(AddFlow.building, F.text)
async def type_building(message: Message, state: FSMContext) -> None:
    buildings = [Building(**raw) for raw in (await state.get_data())["options"]]
    building = find_building(buildings, message.text or "")
    if building is None:
        await message.answer(texts.BUILDING_NOT_FOUND)
        return
    await _choose_building(message, state, building)


async def _choose_building(
    event: Message | CallbackQuery, state: FSMContext, building: Building
) -> None:
    if building.cherg_gpv is None:
        await _reject_address(event, state, building)
        return
    await state.update_data(building=asdict(building), label=texts.DEFAULT_LABEL)
    await state.set_state(AddFlow.confirm)
    await _show_confirm(event, state)


async def _reject_address(
    event: Message | CallbackQuery, state: FSMContext, building: Building
) -> None:
    data = await state.get_data()
    address = escape(f"{data['city']['name']}, {data['street']['name']}, {building.name}")
    await state.clear()
    await _respond(event, texts.NO_SCHEDULE_FOR_ADDRESS.format(address=address))


async def _show_confirm(event: Message | CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    address = escape(
        f"{data['city']['name']}, {data['street']['name']}, {data['building']['name']}"
    )
    text = texts.CONFIRM_ADDRESS.format(
        address=address,
        subqueue=escape(subqueue_label(data["building"]["cherg_gpv"])),
        label=escape(data["label"]),
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
    await state.clear()
    city, street, building = (
        City(**data["city"]),
        Street(**data["street"]),
        Building(**data["building"]),
    )
    try:
        await subscriptions.add(user_id, data["label"], city, street, building, _now())
    except NoScheduleForAddress:
        address = escape(f"{city.name}, {street.name}, {building.name}")
        await _respond(callback, texts.NO_SCHEDULE_FOR_ADDRESS.format(address=address))
        return
    await _respond(callback, texts.ADDED.format(label=escape(data["label"])))


@router.callback_query()
async def stale_button(callback: CallbackQuery) -> None:
    await callback.answer(texts.STALE_BUTTON, show_alert=True)

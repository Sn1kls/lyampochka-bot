from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from . import texts


class KnownUser(BaseMiddleware):
    """Passes the internal id of a registered sender to handlers as `user_id`.

    Registration happens only on /start; everyone else is asked to press it first.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = data.get("event_from_user")
        user_id = None
        if from_user is not None:
            user_id = await data["subscriptions"].find_user("telegram", str(from_user.id))
        if user_id is not None:
            data["user_id"] = user_id
        elif not _is_start_command(event):
            if isinstance(event, CallbackQuery):
                await event.answer(texts.START_FIRST, show_alert=True)
            elif isinstance(event, Message):
                await event.answer(texts.START_FIRST)
            return None
        return await handler(event, data)


def _is_start_command(event: TelegramObject) -> bool:
    if not isinstance(event, Message) or not event.text:
        return False
    return event.text.split()[0].partition("@")[0] == "/start"

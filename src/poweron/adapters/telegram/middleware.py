from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.enums import ChatType
from aiogram.types import TelegramObject


class RegisterUser(BaseMiddleware):
    """Resolves the internal user id of the sender and passes it to handlers as `user_id`."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = data.get("event_from_user")
        chat = data.get("event_chat")
        if from_user is not None and chat is not None and chat.type == ChatType.PRIVATE:
            data["user_id"] = await data["subscriptions"].register(
                "telegram", str(from_user.id), "telegram", str(chat.id)
            )
        return await handler(event, data)

"""Error reports to Sentry, without addresses or secrets."""

import json
from collections.abc import Callable
from importlib.metadata import version
from typing import Any

import sentry_sdk

from poweron.config import Settings

Event = dict[str, Any]


def init_sentry(settings: Settings) -> None:
    """Report errors to Sentry when SENTRY_DSN is set; otherwise do nothing."""
    if options := sentry_options(settings):
        sentry_sdk.init(**options)


def sentry_options(settings: Settings) -> dict[str, Any] | None:
    """`sentry_sdk.init` options, or None without a DSN.

    Addresses must not leave the server: handlers keep them in local variables, and toe API
    requests carry them in the URL. So the SDK sends no local variables (and no user data: the default). It also
    runs no auto-enabled integrations: httpx, aiohttp and SQLAlchemy record URLs and queries as
    breadcrumbs, and aiogram's Telegram URLs contain the bot token. The default integrations stay:
    `logger.exception(...)` becomes an event, uncaught exceptions too, and INFO logs become
    breadcrumbs (they carry no personal data by the project's logging rule).
    """
    if settings.sentry_dsn is None:
        return None
    return {
        "dsn": settings.sentry_dsn.get_secret_value(),
        "release": f"poweron@{version('poweron')}+{settings.git_sha}",
        "environment": settings.sentry_environment,
        "include_local_variables": False,
        "auto_enabling_integrations": False,
        "before_send": _without(settings.bot_token.get_secret_value()),
    }


def _without(secret: str) -> Callable[[Event, Any], Event]:
    """A last guard: the bot token never leaves, wherever it ended up in an event."""

    def before_send(event: Event, hint: Any) -> Event:
        serialized = json.dumps(event, default=str)
        if secret not in serialized:
            return event
        cleaned: Event = json.loads(serialized.replace(secret, "[bot token]"))
        return cleaned

    return before_send

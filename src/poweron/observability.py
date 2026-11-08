"""Error reports to Sentry, without addresses or secrets."""

from importlib.metadata import version
from typing import Any

import sentry_sdk

from poweron.config import Settings


def init_sentry(settings: Settings) -> None:
    """Report errors to Sentry when SENTRY_DSN is set; otherwise do nothing."""
    if options := sentry_options(settings):
        sentry_sdk.init(**options)


def sentry_options(settings: Settings) -> dict[str, Any] | None:
    """`sentry_sdk.init` options, or None without a DSN.

    Addresses live in local variables and toe API URLs, and the bot token in Telegram URLs,
    so: no local variables and no auto-enabled HTTP/SQL integrations (their breadcrumbs).
    """
    if settings.sentry_dsn is None:
        return None
    token = settings.bot_token.get_secret_value()
    # The part after the colon is the secret; it may also appear URL-encoded around it.
    secrets = (token, token.partition(":")[2])

    def before_send(event: dict[str, Any], hint: Any) -> Any:
        """A last guard: the bot token never leaves, wherever it ended up in an event."""
        return _scrub(event, secrets)

    return {
        "dsn": settings.sentry_dsn.get_secret_value(),
        "release": f"poweron@{version('poweron')}+{settings.git_sha}",
        "environment": settings.sentry_environment,
        "include_local_variables": False,
        "auto_enabling_integrations": False,
        "before_send": before_send,
    }


def _scrub(value: Any, secrets: tuple[str, ...]) -> Any:
    """`value` with every secret replaced in its strings; other types are kept as they are."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[bot token]")
        return value
    if isinstance(value, dict):
        return {key: _scrub(item, secrets) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, secrets) for item in value]
    return value

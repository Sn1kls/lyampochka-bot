from poweron.adapters.telegram.bot import build_dispatcher, create_bot


def test_dispatcher_carries_services_and_bot_defaults_to_html() -> None:
    services: dict[str, object] = {"subscriptions": 1, "catalog": 2, "schedules": 3}
    dispatcher = build_dispatcher(**services)  # type: ignore[arg-type]

    assert dispatcher.workflow_data == services
    bot = create_bot("123:abc")
    assert bot.default.parse_mode == "HTML"
    assert bot.default.link_preview_is_disabled is True

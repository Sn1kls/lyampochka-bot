import pytest

from poweron.config import Settings


def test_empty_values_in_env_fall_back_to_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:secret")
    monkeypatch.setenv("ADMIN_CHAT_ID", "")
    monkeypatch.setenv("CONTACT", "")

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.admin_chat_id is None
    assert settings.contact == "n/a"
    assert settings.poll_interval_sec == 300
    assert "secret" not in repr(settings)

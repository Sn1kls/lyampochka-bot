import os
import subprocess
import sys
from pathlib import Path

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


def test_env_file_replaces_dot_env_instead_of_layering_on_it(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "BOT_TOKEN=1:production\nCONTACT=production\nHEALTHCHECK_URL=https://hc/prod\n"
    )
    (tmp_path / ".env.staging").write_text("BOT_TOKEN=2:staging\nCONTACT=staging\n")
    script = (
        "from poweron.config import Settings; s = Settings(); print(s.contact, s.healthcheck_url)"
    )
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"BOT_TOKEN", "CONTACT", "HEALTHCHECK_URL"}
    }

    # A fresh interpreter: the file is chosen when the module is imported.
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env={**environment, "ENV_FILE": ".env.staging"},
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.split() == ["staging", "None"]

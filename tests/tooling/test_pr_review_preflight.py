import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".claude" / "skills" / "pr-review" / "preflight.sh"
MIGRATION = "src/poweron/adapters/db/migrations/versions/0001_initial.py"

pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="preflight needs jq")


def git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def commit(repo, path, text):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", f"change {path}")


@pytest.fixture
def repo(tmp_path):
    git(tmp_path, "init", "-q", "-b", "develop")
    commit(tmp_path, MIGRATION, "revision = '0001'\n")
    git(tmp_path, "switch", "-q", "-c", "feature/x")
    return tmp_path


def run_preflight(repo):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment["PR_BASE_REF"] = "develop"
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=repo, env=environment, check=True, capture_output=True, text=True
    )
    return json.loads(result.stdout)


def findings_of(report, check):
    return [finding for finding in report["findings"] if finding["check"] == check]


def test_a_branch_without_commits_has_nothing_to_review(repo):
    report = run_preflight(repo)

    assert report["halt"] is None
    assert (report["files"], report["findings"]) == ([], [])


def test_a_missing_base_branch_halts(repo):
    git(repo, "branch", "-q", "-m", "develop", "old")

    assert "not found" in run_preflight(repo)["halt"]


def test_a_telegram_token_in_an_added_line_is_critical(repo):
    commit(repo, "src/poweron/config.py", 'BOT = "123456789:AAH0123456789abcdefghijklmnopqrstuv"\n')

    [leak] = findings_of(run_preflight(repo), "secret-scan")

    assert leak["severity"] == "CRITICAL"
    assert (leak["file"], leak["start_line"]) == ("src/poweron/config.py", 1)


def test_secret_like_values_in_tests_are_ignored(repo):
    commit(repo, "tests/test_keys.py", 'token = "abcdefghijklmnopqrstuvwxyz123456"\n')

    assert findings_of(run_preflight(repo), "secret-scan") == []


def test_editing_an_applied_migration_is_critical_and_flags_the_check(repo):
    commit(repo, MIGRATION, "revision = '0001'\nchanged = True\n")

    report = run_preflight(repo)

    [edit] = findings_of(report, "migration-edit")
    assert edit["file"] == MIGRATION
    assert {"name": "migration-edit", "status": "flagged", "detail": "1 finding(s)"} in report[
        "checks"
    ]


def test_a_new_migration_is_fine(repo):
    commit(repo, "src/poweron/adapters/db/migrations/versions/0002_next.py", "revision = '0002'\n")

    assert findings_of(run_preflight(repo), "migration-edit") == []


def test_source_change_without_tests_is_a_warning_and_with_tests_is_not(repo):
    commit(repo, "src/poweron/core/services.py", "def run():\n    return 1\n")
    assert len(findings_of(run_preflight(repo), "tests-touched")) == 1

    commit(repo, "tests/test_services.py", "def test_run():\n    assert True\n")
    assert findings_of(run_preflight(repo), "tests-touched") == []


def test_the_patch_leaves_out_fixtures_but_lists_them(repo):
    commit(repo, "tests/fixtures/schedule.json", '{"address": "x"}\n')

    report = run_preflight(repo)

    assert "tests/fixtures/schedule.json" in report["files"]
    assert "schedule.json" not in Path(report["patch"]).read_text()

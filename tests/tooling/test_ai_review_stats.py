import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "ai_review_stats.py"
spec = importlib.util.spec_from_file_location("ai_review_stats", SCRIPT)
ai_review_stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ai_review_stats)

TRANSCRIPT = [
    {"type": "system", "subtype": "init"},
    {"type": "assistant", "message": {"content": []}},
    {
        "type": "result",
        "num_turns": 18,
        "duration_ms": 151_000,
        "total_cost_usd": 0.04251,
        "modelUsage": {
            "claude-haiku-5-5": {
                "costUSD": 0.03,
                "inputTokens": 20,
                "outputTokens": 8000,
                "cacheReadInputTokens": 350_000,
                "cacheCreationInputTokens": 100_000,
            },
            "other": {"inputTokens": 2, "outputTokens": 877},
        },
        "permission_denials": [
            {"tool_name": "Bash", "tool_input": {"command": "PR_BASE_REF=x preflight.sh --ci"}},
            {"tool_name": "WebFetch", "tool_input": {"url": "https://x"}},
        ],
    },
]


def stats():
    return ai_review_stats.build_stats(TRANSCRIPT, model="claude-haiku-5-5")


def test_cost_comes_from_the_transcript():
    assert stats()["cost_usd"] == 0.0425


def test_tokens_are_summed_across_models():
    result = stats()

    assert result["input_tokens"] == 22
    assert result["output_tokens"] == 8877
    assert result["cache_read_tokens"] == 350_000
    assert result["cache_write_tokens"] == 100_000
    assert result["turns"] == 18


def test_cost_is_split_by_model_in_the_job_summary():
    summary = ai_review_stats.job_summary(stats())

    assert stats()["cost_by_model"] == {"claude-haiku-5-5": 0.03}
    assert "| Cost on `claude-haiku-5-5` | $0.0300 |" in summary


def test_permission_denials_name_the_command_or_tool():
    assert stats()["permission_denials"] == ["PR_BASE_REF=x preflight.sh --ci", "WebFetch"]


def test_a_run_that_never_started_still_has_stats():
    result = ai_review_stats.build_stats([], model="m")

    assert (result["turns"], result["cost_usd"]) == (None, None)
    assert "**Cost:** unknown" in ai_review_stats.cost_line(result)
    assert result["output_tokens"] == 0
    assert "? turns" in ai_review_stats.cost_line(result)


def test_cost_line():
    assert ai_review_stats.cost_line(stats()) == (
        "**Cost:** $0.0425 · 450k in (350k cached) / 9k out · 18 turns · 2m 31s"
    )


def test_job_summary_lists_denials():
    summary = ai_review_stats.job_summary(stats())

    assert "| Cost | $0.0425 |" in summary
    assert "Permission denials (2)" in summary
    assert "- `PR_BASE_REF=x preflight.sh --ci`" in summary


def test_main_writes_stats_and_the_job_summary(tmp_path, monkeypatch):
    transcript = tmp_path / "execution.json"
    transcript.write_text(json.dumps(TRANSCRIPT))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("AI_REVIEW_MODEL", "claude-haiku-5-5")

    ai_review_stats.main(
        ["--transcript", str(transcript), "--out", str(tmp_path / "run-stats.json")]
    )

    assert json.loads((tmp_path / "run-stats.json").read_text())["cost_usd"] == 0.0425
    assert "## AI review run" in summary.read_text()


def test_main_survives_a_missing_transcript(tmp_path):
    out = tmp_path / "run-stats.json"

    ai_review_stats.main(["--transcript", str(tmp_path / "absent.json"), "--out", str(out)])

    assert json.loads(out.read_text())["cost_usd"] is None

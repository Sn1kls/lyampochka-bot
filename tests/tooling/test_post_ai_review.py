import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".github" / "scripts" / "post_ai_review.py"
spec = importlib.util.spec_from_file_location("post_ai_review", SCRIPT)
post_ai_review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(post_ai_review)

PATCH = "\n".join(
    [
        "@@ -10,4 +10,6 @@ def view(request):",
        " context = 1",
        "-old = 2",
        "+new = 2",
        "+extra = 3",
        " tail = 4",
        "\\ No newline at end of file",
        "@@ -40,2 +42,3 @@ class Foo:",
        " a = 1",
        "+b = 2",
        " c = 3",
    ]
)


def finding(**overrides):
    base = {
        "severity": "CRITICAL",
        "category": "security",
        "title": "Raw SQL built from request data",
        "file": "src/poweron/core/services.py",
        "start_line": 11,
        "end_line": 11,
        "rationale": "f-string interpolates request.GET into cursor.execute.",
        "suggestion": "Pass parameters separately.",
        "confidence": 0.95,
    }
    base.update(overrides)
    return base


def report(findings, verdict="request_changes"):
    return {
        "verdict": verdict,
        "summary_markdown": "Adds a deal search view.",
        "counts": {"CRITICAL": 1, "WARNING": 0, "SUGGESTION": 0},
        "checks": [{"name": "secret-scan", "status": "ok", "detail": ""}],
        "findings": findings,
    }


def thread(key, thread_id="T1", resolved_by=None, author="github-actions", path=None, line=None):
    return {
        "id": thread_id,
        "isResolved": resolved_by is not None,
        "resolvedBy": {"login": resolved_by} if resolved_by else None,
        "path": path,
        "line": line,
        "comments": {
            "nodes": [
                {"author": {"login": author}, "body": f"x\n<!-- ai-pr-review:finding:{key} -->"}
            ]
        },
    }


class FakeGitHub:
    def __init__(self, threads=(), issue_comments=(), reject_review=False, forbid_resolve=False):
        self.threads = list(threads)
        self.forbid_resolve = forbid_resolve
        self.issue_comments = list(issue_comments)
        self.reject_review = reject_review
        self.calls = []
        self.resolved = []

    def paginate(self, path):
        if path.endswith("/files"):
            return [{"filename": "src/poweron/core/services.py", "patch": PATCH}]
        return self.issue_comments

    def review_threads(self, pr_number):
        return self.threads

    def resolve_thread(self, thread_id):
        if self.forbid_resolve:
            raise RuntimeError("GraphQL error: Resource not accessible by integration")
        self.resolved.append(thread_id)

    def request(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        if path.endswith("/reviews") and self.reject_review:
            raise urllib.error.HTTPError(
                path, 422, "Unprocessable", {}, io.BytesIO(b'{"message":"line"}')
            )


def test_parse_hunks_keeps_only_new_side_lines():
    lines = post_ai_review.parse_hunks([{"filename": "a.py", "patch": PATCH}])["a.py"]

    assert lines == {10, 11, 12, 13, 42, 43, 44}


def test_parse_hunks_handles_files_without_patch():
    assert post_ai_review.parse_hunks([{"filename": "img.png"}]) == {"img.png": set()}


def test_finding_outside_the_diff_is_not_posted_inline():
    commentable = {"src/poweron/core/services.py": {10, 11}}

    comments, status = post_ai_review.select_inline([finding(start_line=99)], commentable, set())

    assert comments == []
    assert status[post_ai_review.finding_key(finding())] == "outside diff"


def test_multi_line_finding_becomes_a_range_comment():
    commentable = {"src/poweron/core/services.py": {10, 11, 12}}

    comments, _ = post_ai_review.select_inline(
        [finding(start_line=10, end_line=12)], commentable, set()
    )

    assert comments[0]["start_line"] == 10
    assert comments[0]["line"] == 12


def test_range_that_leaves_the_hunk_falls_back_to_the_first_line():
    commentable = {"src/poweron/core/services.py": {10, 11}}

    comments, _ = post_ai_review.select_inline(
        [finding(start_line=11, end_line=30)], commentable, set()
    )

    assert comments[0]["line"] == 11
    assert "start_line" not in comments[0]


@pytest.mark.parametrize(
    ("severity", "confidence", "inline"),
    [
        ("CRITICAL", 0.5, True),
        ("WARNING", 0.8, True),
        ("WARNING", 0.79, False),
        ("SUGGESTION", 1.0, False),
    ],
)
def test_inline_threshold(severity, confidence, inline):
    commentable = {"src/poweron/core/services.py": {11}}

    comments, _ = post_ai_review.select_inline(
        [finding(severity=severity, confidence=confidence)], commentable, set()
    )

    assert bool(comments) is inline


def test_inline_comments_are_capped_and_criticals_go_first():
    commentable = {"src/poweron/core/services.py": set(range(1, 100))}
    warnings = [finding(severity="WARNING", title=f"warn {n}", start_line=n) for n in range(1, 11)]
    critical = finding(title="the critical one", start_line=50)

    comments, status = post_ai_review.select_inline(warnings + [critical], commentable, set())

    assert len(comments) == post_ai_review.INLINE_LIMIT
    assert "the critical one" in comments[0]["body"]
    assert list(status.values()).count("inline limit") == 3


def test_finding_posted_on_an_earlier_run_is_not_posted_again():
    already = post_ai_review.finding_key(finding())
    commentable = {"src/poweron/core/services.py": {11, 12}}

    comments, status = post_ai_review.select_inline(
        [finding(start_line=12)], commentable, {already}
    )

    assert comments == []
    assert status[already] == "posted earlier"


def test_posted_keys_only_trust_the_bot():
    threads = [thread("abcdefabcdef"), thread("111111111111", author="someone")]

    assert post_ai_review.posted_finding_keys(threads) == {"abcdefabcdef"}


def test_a_thread_a_human_resolved_is_not_posted_again():
    threads = [thread("abcdefabcdef", resolved_by="serhii")]

    assert post_ai_review.posted_finding_keys(threads) == {"abcdefabcdef"}


def test_a_finding_that_returns_after_the_bot_resolved_it_is_posted_again():
    key = post_ai_review.finding_key(finding())
    gh = FakeGitHub(threads=[thread(key, resolved_by="github-actions")])

    post_ai_review.publish(gh, 7, report([finding()]), head_sha="a" * 40, model="m", run_url="u")

    assert any(call[1].endswith("/reviews") for call in gh.calls)


def test_threads_for_findings_no_longer_reported_are_resolved():
    current = post_ai_review.finding_key(finding())
    threads = [
        thread(current, "keep"),
        thread("aaaaaaaaaaaa", "fixed"),
        thread("bbbbbbbbbbbb", "already", resolved_by="serhii"),
        thread("cccccccccccc", "human", author="serhii"),
    ]
    gh = FakeGitHub(threads=threads)

    post_ai_review.publish(gh, 7, report([finding()]), head_sha="a" * 40, model="m", run_url="u")

    assert gh.resolved == ["fixed"]
    assert "Resolved:** 1 earlier thread" in gh.calls[-1][2]["body"]


def test_a_reworded_finding_on_a_line_the_bot_already_commented_is_not_posted_again():
    gh = FakeGitHub(
        threads=[thread("aaaaaaaaaaaa", "old", path="src/poweron/core/services.py", line=11)]
    )

    post_ai_review.publish(
        gh, 7, report([finding(title="Reworded title")]), head_sha="a" * 40, model="m", run_url="u"
    )

    assert not any(call[1].endswith("/reviews") for call in gh.calls)
    assert gh.resolved == []
    assert "posted earlier" in gh.calls[-1][2]["body"]


def test_an_outdated_thread_does_not_block_a_comment_on_its_old_line():
    gh = FakeGitHub(
        threads=[thread("aaaaaaaaaaaa", "old", path="src/poweron/core/services.py", line=None)]
    )

    post_ai_review.publish(
        gh, 7, report([finding(title="Reworded title")]), head_sha="a" * 40, model="m", run_url="u"
    )

    assert any(call[1].endswith("/reviews") for call in gh.calls)
    assert gh.resolved == ["old"]


def test_a_thread_that_cannot_be_resolved_does_not_lose_the_summary():
    gh = FakeGitHub(threads=[thread("aaaaaaaaaaaa", "fixed")], forbid_resolve=True)

    post_ai_review.publish(gh, 7, report([finding()]), head_sha="a" * 40, model="m", run_url="u")

    method, path, payload = gh.calls[-1]
    assert (method, path) == ("POST", "/issues/7/comments")
    assert "Resolved:" not in payload["body"]


def test_nothing_is_resolved_after_a_failed_review():
    gh = FakeGitHub(threads=[thread("aaaaaaaaaaaa", "fixed")])

    post_ai_review.publish(
        gh, 7, {**report([]), "incomplete": True}, head_sha="a" * 40, model="m", run_url="u"
    )

    assert gh.resolved == []


def test_publish_posts_one_comment_review_and_a_new_summary():
    gh = FakeGitHub()

    post_ai_review.publish(gh, 7, report([finding()]), head_sha="a" * 40, model="m", run_url="u")

    review = next(call for call in gh.calls if call[1].endswith("/reviews"))
    assert review[2]["event"] == "COMMENT"
    assert review[2]["commit_id"] == "a" * 40
    assert len(review[2]["comments"]) == 1
    summary = next(call for call in gh.calls if call[1] == "/issues/7/comments")
    assert summary[0] == "POST"
    assert post_ai_review.SUMMARY_MARKER in summary[2]["body"]


def test_publish_edits_the_existing_summary_and_skips_an_empty_review():
    existing = {
        "id": 55,
        "user": {"login": "github-actions[bot]"},
        "body": post_ai_review.SUMMARY_MARKER,
    }
    gh = FakeGitHub(issue_comments=[existing])

    post_ai_review.publish(
        gh, 7, report([], verdict="approve"), head_sha="a" * 40, model="m", run_url="u"
    )

    assert [call[:2] for call in gh.calls] == [("PATCH", "/issues/comments/55")]
    assert "Looks good" in gh.calls[0][2]["body"]


def test_rejected_review_still_publishes_the_summary():
    gh = FakeGitHub(reject_review=True)

    post_ai_review.publish(gh, 7, report([finding()]), head_sha="a" * 40, model="m", run_url="u")

    summary = gh.calls[-1][2]["body"]
    assert "rejected by GitHub" in summary
    assert "Raw SQL built from request data" in summary


def test_summary_escapes_table_cells():
    body = post_ai_review.render_summary(
        report([finding(title="a | b")]), {}, head_sha="abc1234def", model="m", run_url="u"
    )

    assert "a \\| b" in body


def test_missing_report_turns_into_a_failure_notice(tmp_path):
    loaded = post_ai_review.load_report(tmp_path / "absent.json")

    assert loaded["findings"] == []
    assert "did not complete" in loaded["summary_markdown"]


def test_failure_notice_does_not_claim_a_verdict(tmp_path):
    body = post_ai_review.render_summary(
        post_ai_review.load_report(tmp_path / "absent.json"),
        {},
        head_sha="abc1234",
        model="m",
        run_url="u",
    )

    assert "Review incomplete" in body
    assert "nothing critical" not in body


def test_invalid_report_turns_into_a_failure_notice(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("{not json")

    assert "not valid JSON" in post_ai_review.load_report(path)["summary_markdown"]


def test_summary_shows_the_run_cost_when_stats_exist(tmp_path):
    path = tmp_path / "run-stats.json"
    path.write_text(
        '{"model": "m", "cost_usd": 0.0425, "turns": 18, "duration_ms": 151000, '
        '"input_tokens": 22, "cache_read_tokens": 350000, "cache_write_tokens": 100000, "output_tokens": 8877, '
        '"permission_denials": []}'
    )
    stats = post_ai_review.load_stats(str(path))

    body = post_ai_review.render_summary(
        report([]), {}, head_sha="abc1234", model="m", run_url="u", stats=stats
    )

    assert "**Cost:** $0.0425" in body


def test_missing_stats_only_drop_the_cost_line(tmp_path):
    assert post_ai_review.load_stats(str(tmp_path / "absent.json")) is None
    assert post_ai_review.load_stats(None) is None


def test_an_api_key_the_model_echoed_is_never_posted():
    leaked = "sk-ant-api03-abcdefghijklmnop"
    gh = FakeGitHub()
    leaky = {**report([finding(rationale=f"env has {leaked}")]), "summary_markdown": leaked}

    post_ai_review.publish(gh, 7, leaky, head_sha="a" * 40, model="m", run_url="u")

    posted = json.dumps([call[2] for call in gh.calls])
    assert leaked not in posted
    assert "[redacted]" in posted

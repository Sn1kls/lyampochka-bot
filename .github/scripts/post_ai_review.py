"""Publish the pr-review CI report to a pull request.

Runs in the `publish` job of .github/workflows/ai-pr-review.yml, which holds a
write-scoped GITHUB_TOKEN and no LLM key. Everything here is deterministic: the
model decided what it found, this script decides what reaches the PR.

- CRITICAL findings, and WARNING findings with confidence >= INLINE_MIN_CONFIDENCE,
  become inline comments in one review with event=COMMENT, at most INLINE_LIMIT,
  and only on lines GitHub accepts (the new side of a diff hunk).
- Findings already posted on an earlier run (matched by a hidden marker) are not
  posted again, unless the bot itself resolved that thread and the finding came back.
  A thread a human resolved stays resolved: that is a decision, not noise.
- Bot threads whose finding is no longer reported are resolved, but only after a
  complete review; a failed run resolves nothing.
- Everything lands in one summary comment that is edited in place on every run.

Stdlib only, so the job needs no dependency install.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ai_review_stats  # noqa: E402

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
SUMMARY_MARKER = "<!-- ai-pr-review:summary -->"
FINDING_MARKER = re.compile(r"<!-- ai-pr-review:finding:([0-9a-f]{12}) -->")
BOT_LOGIN = "github-actions[bot]"
BOT_LOGINS = {BOT_LOGIN, "github-actions"}
INLINE_LIMIT = 8
INLINE_MIN_CONFIDENCE = 0.8
SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "SUGGESTION": 2}
SEVERITY_ICON = {"CRITICAL": "🔴", "WARNING": "🟡", "SUGGESTION": "🔵"}
VERDICT_TEXT = {
    "request_changes": "🔴 **Would request changes** — critical issues found",
    "comment": "🟡 **Comments** — nothing critical, some points worth a look",
    "approve": "🟢 **Looks good** — no issues found",
}
# The review job's agent can read its own environment; a prompt-injected PR could ask it to
# echo the Anthropic key into the report, and this job would post it.
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")
HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_hunks(pr_files):
    """Map each file to the set of new-side line numbers a review comment may target."""
    commentable = {}
    for entry in pr_files:
        lines = set()
        new_line = 0
        for raw in (entry.get("patch") or "").splitlines():
            header = HUNK_HEADER.match(raw)
            if header:
                new_line = int(header.group(1))
                continue
            if raw.startswith("-") or raw.startswith("\\"):
                continue
            lines.add(new_line)
            new_line += 1
        commentable[entry["filename"]] = lines
    return commentable


def finding_key(finding):
    """Identity of a finding across runs. Line numbers shift on every push, so they are left out."""
    raw = f"{finding['file']}|{finding['title'].strip().lower()}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def is_inline_candidate(finding):
    if finding["severity"] == "CRITICAL":
        return True
    return (
        finding["severity"] == "WARNING" and finding.get("confidence", 0) >= INLINE_MIN_CONFIDENCE
    )


def anchor(finding, commentable):
    """Return (start_line, line) for a review comment, or None when GitHub would reject it."""
    lines = commentable.get(finding["file"])
    if not lines:
        return None
    start = finding.get("start_line")
    end = finding.get("end_line") or start
    if start not in lines:
        return None
    if end > start and end in lines and all(n in lines for n in range(start, end + 1)):
        return start, end
    return start, start


def sort_findings(findings):
    return sorted(
        findings, key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9), -f.get("confidence", 0))
    )


def finding_locations(findings, commentable):
    """(path, line) each finding would be commented on, for findings inside the diff."""
    locations = set()
    for finding in findings:
        position = anchor(finding, commentable)
        if position:
            locations.add((finding["file"], position[1]))
    return locations


def select_inline(findings, commentable, posted_keys, posted_locations=frozenset()):
    """Split findings into inline comments to post now, and the per-finding inline status for the summary.

    A finding counts as posted when its key matches an earlier thread, or when an earlier bot thread
    sits on the same line: the model rewords titles between runs, which changes the key.
    """
    comments = []
    status = {}
    for finding in sort_findings(findings):
        key = finding_key(finding)
        if not is_inline_candidate(finding):
            status[key] = "summary"
            continue
        if key in posted_keys:
            status[key] = "posted earlier"
            continue
        position = anchor(finding, commentable)
        if position is None:
            status[key] = "outside diff"
            continue
        if (finding["file"], position[1]) in posted_locations:
            status[key] = "posted earlier"
            continue
        if len(comments) >= INLINE_LIMIT:
            status[key] = "inline limit"
            continue
        start, line = position
        comment = {
            "path": finding["file"],
            "line": line,
            "side": "RIGHT",
            "body": render_inline(finding, key),
        }
        if start != line:
            comment["start_line"] = start
            comment["start_side"] = "RIGHT"
        comments.append(comment)
        status[key] = "inline"
    return comments, status


def render_inline(finding, key):
    parts = [
        f"{SEVERITY_ICON.get(finding['severity'], '')} **{finding['severity']}** · {finding['category']}",
        "",
        f"**{finding['title']}**",
        "",
        finding["rationale"],
    ]
    if finding.get("suggestion"):
        parts += ["", f"**Suggestion:** {finding['suggestion']}"]
    parts += ["", f"<!-- ai-pr-review:finding:{key} -->"]
    return SECRET.sub("[redacted]", "\n".join(parts))


def escape_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def render_summary(report, status, *, head_sha, model, run_url, resolved=0, stats=None):
    counts = report.get("counts", {})
    findings = sort_findings(report.get("findings", []))
    out = [
        SUMMARY_MARKER,
        "## Automated review",
        "",
        "⚠️ **Review incomplete** — no verdict, see below"
        if report.get("incomplete")
        else VERDICT_TEXT.get(report.get("verdict"), report.get("verdict", "")),
        "",
        " · ".join(
            f"{SEVERITY_ICON[s]} {counts.get(s, 0)} {s.lower()}"
            for s in ("CRITICAL", "WARNING", "SUGGESTION")
        ),
        "",
        report.get("summary_markdown", "").strip(),
        "",
    ]
    if findings:
        out += ["| | Where | Finding | Inline |", "|---|---|---|---|"]
        for finding in findings:
            key = finding_key(finding)
            out.append(
                f"| {SEVERITY_ICON.get(finding['severity'], '')} | `{escape_cell(finding['file'])}:"
                f"{finding.get('start_line')}` | {escape_cell(finding['title'])} | "
                f"{status.get(key, 'summary')} |"
            )
        details = [f for f in findings if status.get(finding_key(f)) != "inline"]
        if details:
            out += ["", "<details><summary>Details of findings not posted inline</summary>", ""]
            for finding in details:
                out.append(
                    f"- **{escape_cell(finding['title'])}** — `{finding['file']}:{finding.get('start_line')}` "
                    f"({finding['severity']}): {escape_cell(finding['rationale'])}"
                )
                if finding.get("suggestion"):
                    out.append(f"  - Suggestion: {escape_cell(finding['suggestion'])}")
            out += ["", "</details>"]
        out.append("")

    checks = report.get("checks", [])
    if checks:
        out.append(
            "**Checks:** "
            + " · ".join(
                f"{c['name']} {c['status']}" + (f" ({c['detail']})" if c.get("detail") else "")
                for c in checks
            )
        )
    if resolved:
        out.append(
            f"**Resolved:** {resolved} earlier thread(s) whose finding is no longer reported."
        )
    if stats:
        out.append(ai_review_stats.cost_line(stats))
    out += [
        "",
        f"<sub>Recommendation only — this bot cannot approve or block. Comment `/ai-review` to run it again. "
        f"Commit `{head_sha[:7]}` · model `{model}` · [run]({run_url})</sub>",
    ]
    return SECRET.sub("[redacted]", "\n".join(out))


class GitHub:
    def __init__(self, token, repo):
        self.token = token
        self.repo = repo

    def request(self, method, path, payload=None):
        url = path if path.startswith("http") else f"{API}/repos/{self.repo}{path}"
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
            return json.loads(body) if body else None

    def graphql(self, query, variables):
        result = self.request("POST", GRAPHQL, {"query": query, "variables": variables})
        if result.get("errors"):
            raise RuntimeError(f"GraphQL error: {result['errors']}")
        return result["data"]

    def review_threads(self, pr_number):
        owner, name = self.repo.split("/")
        threads = []
        cursor = None
        while True:
            data = self.graphql(
                REVIEW_THREADS_QUERY,
                {"owner": owner, "name": name, "number": pr_number, "cursor": cursor},
            )
            page = data["repository"]["pullRequest"]["reviewThreads"]
            threads.extend(page["nodes"])
            if not page["pageInfo"]["hasNextPage"]:
                return threads
            cursor = page["pageInfo"]["endCursor"]

    def resolve_thread(self, thread_id):
        self.graphql(RESOLVE_THREAD_MUTATION, {"id": thread_id})

    def paginate(self, path):
        items = []
        page = 1
        while True:
            sep = "&" if "?" in path else "?"
            batch = self.request("GET", f"{path}{sep}per_page=100&page={page}")
            items.extend(batch)
            if len(batch) < 100:
                return items
            page += 1


REVIEW_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          resolvedBy { login }
          path
          line
          comments(first: 1) { nodes { author { login } body } }
        }
      }
    }
  }
}
"""

RESOLVE_THREAD_MUTATION = """
mutation($id: ID!) {
  resolveReviewThread(input: {threadId: $id}) { thread { id } }
}
"""


def bot_threads(threads):
    """Yield (thread, finding key) for review threads the bot started."""
    for thread in threads:
        first = (thread.get("comments", {}).get("nodes") or [{}])[0]
        if (first.get("author") or {}).get("login") not in BOT_LOGINS:
            continue
        match = FINDING_MARKER.search(first.get("body", ""))
        if match:
            yield thread, match.group(1)


def resolved_by_bot(thread):
    return thread.get("isResolved") and (thread.get("resolvedBy") or {}).get("login") in BOT_LOGINS


def posted_finding_keys(threads):
    """Keys that must not be posted again: open bot threads, and bot threads a human resolved."""
    return {key for thread, key in bot_threads(threads) if not resolved_by_bot(thread)}


def posted_locations(threads):
    """(path, line) of bot threads still on the diff, open or resolved by a human."""
    return {
        (thread.get("path"), thread["line"])
        for thread, _ in bot_threads(threads)
        if thread.get("line") and not resolved_by_bot(thread)
    }


def stale_threads(threads, current_keys, current_locations=frozenset()):
    """Open bot threads whose finding the latest review no longer reports, by key or by line."""
    return [
        thread
        for thread, key in bot_threads(threads)
        if not thread["isResolved"]
        and key not in current_keys
        and (thread.get("path"), thread.get("line")) not in current_locations
    ]


def find_summary_comment(issue_comments):
    for comment in issue_comments:
        if comment.get("user", {}).get("login") == BOT_LOGIN and SUMMARY_MARKER in comment.get(
            "body", ""
        ):
            return comment
    return None


def publish(gh, pr_number, report, *, head_sha, model, run_url, stats=None, dry_run=False):
    pr_files = gh.paginate(f"/pulls/{pr_number}/files")
    commentable = parse_hunks(pr_files)
    threads = gh.review_threads(pr_number)
    findings = report.get("findings", [])
    comments, status = select_inline(
        findings, commentable, posted_finding_keys(threads), posted_locations(threads)
    )

    stale, resolved = [], 0
    # Resolving on a failed run would close threads for findings nobody re-checked.
    if not report.get("incomplete"):
        stale = stale_threads(
            threads, {finding_key(f) for f in findings}, finding_locations(findings, commentable)
        )
        for thread in [] if dry_run else stale:
            try:
                gh.resolve_thread(thread["id"])
                resolved += 1
            except (RuntimeError, urllib.error.HTTPError) as error:
                # A thread left open is harmless; losing the summary over it is not.
                print(f"Could not resolve thread {thread['id']}: {error}", file=sys.stderr)

    if comments and not dry_run:
        review = {
            "commit_id": head_sha,
            "event": "COMMENT",
            "body": f"Automated review: {len(comments)} inline finding(s). The summary is in the conversation tab.",
            "comments": comments,
        }
        try:
            gh.request("POST", f"/pulls/{pr_number}/reviews", review)
        except urllib.error.HTTPError as error:
            if error.code != 422:
                raise
            print(
                f"Inline review rejected (422): {error.read().decode(errors='replace')}",
                file=sys.stderr,
            )
            for key, value in status.items():
                if value == "inline":
                    status[key] = "rejected by GitHub"

    body = render_summary(
        report,
        status,
        head_sha=head_sha,
        model=model,
        run_url=run_url,
        resolved=len(stale) if dry_run else resolved,
        stats=stats,
    )
    if dry_run:
        print(
            json.dumps(
                {"inline": comments, "resolve": [t["id"] for t in stale], "summary": body}, indent=2
            )
        )
        return

    existing = find_summary_comment(gh.paginate(f"/issues/{pr_number}/comments"))
    if existing:
        gh.request("PATCH", f"/issues/comments/{existing['id']}", {"body": body})
    else:
        gh.request("POST", f"/issues/{pr_number}/comments", {"body": body})


def failure_report(reason):
    return {
        "incomplete": True,
        "verdict": "comment",
        "summary_markdown": f"⚠️ The review did not complete: {reason}",
        "counts": {"CRITICAL": 0, "WARNING": 0, "SUGGESTION": 0},
        "checks": [],
        "findings": [],
    }


def load_report(path):
    try:
        with open(path, encoding="utf-8") as fh:
            report = json.load(fh)
    except FileNotFoundError:
        return failure_report("the review job produced no report — see the workflow run.")
    except json.JSONDecodeError as error:
        return failure_report(f"the report is not valid JSON ({error.msg}).")
    if not isinstance(report, dict) or "findings" not in report:
        return failure_report("the report does not match the expected schema.")
    return report


def load_stats(path):
    """Run statistics are optional: a missing or broken file only drops the cost line."""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("report", help="path to the JSON report from the review job")
    parser.add_argument("--stats", help="path to run-stats.json from ai_review_stats.py")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the payload instead of posting"
    )
    args = parser.parse_args(argv)

    env = os.environ
    gh = GitHub(env["GITHUB_TOKEN"], env["GITHUB_REPOSITORY"])
    publish(
        gh,
        int(env["PR_NUMBER"]),
        load_report(args.report),
        head_sha=env["HEAD_SHA"],
        model=env.get("AI_REVIEW_MODEL", "unknown"),
        run_url=env.get("RUN_URL", ""),
        stats=load_stats(args.stats),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()

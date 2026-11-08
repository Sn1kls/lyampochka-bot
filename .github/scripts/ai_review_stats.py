"""Summarise what an AI review run cost.

Runs in the `review` job of .github/workflows/ai-pr-review.yml, after the
review step:

    ai_review_stats.py --transcript <execution_file> [--out run-stats.json]

Writes run-stats.json (read by post_ai_review.py) and appends a table to the
Actions job summary. Cost, tokens, turns and permission denials all come from
the agent transcript's final `result` message: against the Anthropic API,
its `total_cost_usd` is priced per model.
Stdlib only, no network.
"""

import argparse
import json
import os


def result_message(transcript):
    for message in reversed(transcript or []):
        if message.get("type") == "result":
            return message
    return {}


def build_stats(transcript, *, model):
    result = result_message(transcript)
    per_model = result.get("modelUsage") or {}
    total_cost = result.get("total_cost_usd")
    stats = {
        "model": model,
        "cost_usd": round(total_cost, 4) if total_cost is not None else None,
        "turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "input_tokens": sum(m.get("inputTokens", 0) for m in per_model.values()),
        "cache_read_tokens": sum(m.get("cacheReadInputTokens", 0) for m in per_model.values()),
        "cache_write_tokens": sum(m.get("cacheCreationInputTokens", 0) for m in per_model.values()),
        "output_tokens": sum(m.get("outputTokens", 0) for m in per_model.values()),
        "cost_by_model": {
            name: round(m["costUSD"], 4) for name, m in per_model.items() if "costUSD" in m
        },
        "permission_denials": [
            (d.get("tool_input") or {}).get("command") or d.get("tool_name", "?")
            for d in result.get("permission_denials") or []
        ],
    }
    return stats


def tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)


def duration(ms):
    if not ms:
        return "?"
    seconds = round(ms / 1000)
    return f"{seconds // 60}m {seconds % 60:02d}s"


def cost(stats):
    return "unknown" if stats.get("cost_usd") is None else f"${stats['cost_usd']:.4f}"


def cost_line(stats):
    """One line for the PR summary comment."""
    total_in = stats["input_tokens"] + stats["cache_read_tokens"] + stats["cache_write_tokens"]
    parts = [
        f"**Cost:** {cost(stats)}",
        f"{tokens(total_in)} in ({tokens(stats['cache_read_tokens'])} cached) / {tokens(stats['output_tokens'])} out",
        f"{stats['turns'] or '?'} turns",
    ]
    parts.append(duration(stats.get("duration_ms")))
    return " · ".join(parts)


def job_summary(stats):
    rows = [
        ("Cost", cost(stats)),
        ("Model", f"`{stats['model']}`"),
        *(
            (f"Cost on `{name}`", f"${usd:.4f}")
            for name, usd in (stats.get("cost_by_model") or {}).items()
        ),
        ("Input tokens (uncached)", f"{stats['input_tokens']:,}"),
        ("Cache read tokens", f"{stats['cache_read_tokens']:,}"),
        ("Cache write tokens", f"{stats['cache_write_tokens']:,}"),
        ("Output tokens", f"{stats['output_tokens']:,}"),
        ("Turns", stats["turns"] or "?"),
        ("Duration", duration(stats.get("duration_ms"))),
    ]
    out = ["## AI review run", "", "| | |", "|---|---|", *(f"| {k} | {v} |" for k, v in rows)]
    if stats["permission_denials"]:
        out += ["", f"**Permission denials ({len(stats['permission_denials'])}):**", ""]
        out += [f"- `{d}`" for d in stats["permission_denials"]]
    return "\n".join(out) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transcript", default="")
    parser.add_argument("--out", default="run-stats.json")
    args = parser.parse_args(argv)

    transcript = []
    if args.transcript and os.path.exists(args.transcript):
        with open(args.transcript, encoding="utf-8") as fh:
            transcript = json.load(fh)
    stats = build_stats(transcript, model=os.environ.get("AI_REVIEW_MODEL", "unknown"))

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(job_summary(stats))
    print(cost_line(stats))


if __name__ == "__main__":
    main()

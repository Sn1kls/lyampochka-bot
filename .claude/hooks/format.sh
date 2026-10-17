#!/usr/bin/env bash
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
[ -f pyproject.toml ] || exit 0
uv run --quiet ruff format --quiet . >/dev/null 2>&1
uv run --quiet ruff check --fix --quiet . >/dev/null 2>&1
exit 0

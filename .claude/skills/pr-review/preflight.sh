#!/usr/bin/env bash
# Step 0 of the pr-review skill: deterministic checks on the PR's commits (merge-base..HEAD).
# Prints one JSON object: {halt, base, patch, files, findings, checks}.
# Never runs project code (no uv, pytest, make): in CI it runs on a PR-controlled
# checkout next to an LLM key. PR_BASE_REF picks the base branch (default develop).
set -uo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo '{"halt":"jq is not installed","files":[],"findings":[],"checks":[]}'
  exit 0
fi
cd "$(git rev-parse --show-toplevel)" || exit 1

halt() {
  jq -nc --arg reason "$1" '{halt: $reason, files: [], findings: [], checks: []}'
  exit 0
}

BASE_REF="${PR_BASE_REF:-develop}"
BASE_COMMIT=""
for candidate in "origin/$BASE_REF" "$BASE_REF"; do
  if git rev-parse --verify --quiet "$candidate^{commit}" >/dev/null; then
    BASE_COMMIT="$candidate"
    break
  fi
done
[ -n "$BASE_COMMIT" ] || halt "base branch '$BASE_REF' not found locally or on origin; fetch it first"
BASE=$(git merge-base "$BASE_COMMIT" HEAD 2>/dev/null) || halt "no merge-base with $BASE_COMMIT"
RANGE="$BASE..HEAD"

# The patch the model reads leaves out what it cannot usefully review; the checks still see everything.
NOT_REVIEWED=(':!uv.lock' ':!tests/fixtures/**' ':!*.png' ':!*.jpg' ':!*.jpeg' ':!*.gif' ':!*.ico' ':!*.pdf')
PATCH="$(git rev-parse --absolute-git-dir)/pr-review/diff.patch"
mkdir -p "$(dirname "$PATCH")"
git diff "$RANGE" -- . "${NOT_REVIEWED[@]}" > "$PATCH"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
FILES="$WORK/files.txt"
ADDED="$WORK/added.tsv"
FINDINGS="$WORK/findings.ndjson"
CHECKS="$WORK/checks.ndjson"
: > "$FINDINGS"
: > "$CHECKS"

git diff --name-only --diff-filter=d "$RANGE" > "$FILES"
if [ ! -s "$FILES" ]; then
  jq -nc --arg base "$BASE" '{halt: null, base: $base, files: [], findings: [], checks: []}'
  exit 0
fi

# file <TAB> new-side line <TAB> content, for every added line.
git diff -U0 --diff-filter=d "$RANGE" | awk '
  /^\+\+\+ / { file = substr($0, 7); next }
  /^@@/ { match($0, /\+[0-9]+/); line = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
  /^\+/ { print file "\t" line "\t" substr($0, 2); line++ }
' > "$ADDED"

# emit_finding check severity category title file line rationale suggestion
emit_finding() {
  jq -nc --arg check "$1" --arg severity "$2" --arg category "$3" --arg title "$4" \
    --arg file "$5" --argjson line "$6" --arg rationale "$7" --arg suggestion "$8" \
    '{check: $check, severity: $severity, category: $category, title: $title, file: $file,
      start_line: $line, end_line: $line, rationale: $rationale, suggestion: $suggestion,
      confidence: 1}' >> "$FINDINGS"
}

# A check that produced findings reports "flagged", never "ok".
emit_check() {
  local count
  count=$(jq -c --arg check "$1" 'select(.check == $check)' "$FINDINGS" | wc -l | tr -d ' ')
  if [ "$count" -gt 0 ]; then
    jq -nc --arg name "$1" --arg detail "$count finding(s)" '{name: $name, status: "flagged", detail: $detail}' >> "$CHECKS"
  else
    jq -nc --arg name "$1" '{name: $name, status: "ok", detail: ""}' >> "$CHECKS"
  fi
}

check_secrets() {
  local pattern='sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|AKIA[0-9A-Z]{16}|[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(api[_-]?key|secret|password|passwd|token)[A-Za-z_]*["]?[[:space:]]*[:=][[:space:]]*["'"'"'][A-Za-z0-9/+_.=-]{16,}["'"'"']'
  while IFS=$'\t' read -r file line _content; do
    case "$file" in
      tests/*|*.example|*.md) continue ;;
    esac
    emit_finding secret-scan CRITICAL security "Possible secret in an added line" "$file" "$line" \
      "An added line matches a credential pattern. A secret that reaches a pushed commit stays in git history and must be rotated, not just deleted." \
      "Read the value from the environment (.env, documented in .env.example) and rotate it if it was ever pushed."
  done < <(awk -F'\t' -v pattern="$pattern" '$3 ~ pattern' "$ADDED")
  emit_check secret-scan
}

check_migration_edits() {
  while IFS= read -r file; do
    emit_finding migration-edit CRITICAL bug "Existing migration was edited" "$file" 1 \
      "This Alembic revision already exists on the base branch. Databases that applied it (production) will not run it again, so the schema in code and the real schema diverge." \
      "Revert the edit and add a new revision with 'alembic revision'."
  done < <(git diff --name-status "$RANGE" | awk -F'\t' '$1 ~ /^M/ && $2 ~ /^src\/poweron\/adapters\/db\/migrations\/versions\/.*[.]py$/ { print $2 }')
  emit_check migration-edit
}

check_tests_touched() {
  local source_file
  source_file=$(grep -E '^src/poweron/.*[.]py$' "$FILES" | grep -vE '/migrations/|/__init__[.]py$|/texts[.]py$' | head -1)
  if [ -n "$source_file" ] && ! grep -qE '^tests/' "$FILES"; then
    emit_finding tests-touched WARNING test "Behaviour changed with no test touched" "$source_file" 1 \
      "The PR changes code under src/poweron/ without adding or updating anything under tests/." \
      "Add a test for the changed behaviour, or say in the PR why the existing suite already covers it."
  fi
  emit_check tests-touched
}

check_large_files() {
  local file size
  while IFS= read -r file; do
    [ -f "$file" ] || continue
    size=$(wc -c < "$file" | tr -d ' ')
    if [ "$size" -gt 1048576 ]; then
      emit_finding large-files WARNING style "Large file added to the repository" "$file" 1 \
        "This file is $((size / 1024)) KB. It stays in git history forever and slows every clone." \
        "Keep it out of the repo, or trim it to the part a test actually needs."
    fi
  done < <(git diff --name-status "$RANGE" | awk -F'\t' '$1 ~ /^A/ { print $2 }')
  emit_check large-files
}

check_secrets
check_migration_edits
check_tests_touched
check_large_files

jq -nc --arg base "$BASE" --arg patch "$PATCH" \
  --rawfile files "$FILES" --slurpfile findings "$FINDINGS" --slurpfile checks "$CHECKS" \
  '{halt: null, base: $base, patch: $patch,
    files: ($files | split("\n") | map(select(length > 0))),
    findings: $findings, checks: $checks}'

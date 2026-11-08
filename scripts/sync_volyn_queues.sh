#!/bin/sh
# Weekly Volyn queue sync, run on the owner's Mac (a Ukrainian IP: the server is challenged
# by Cloudflare on energy.volyn.ua). Exports the address → queue table and pipes it into
# the bot, which replaces its catalogue in one transaction. The import runs in its own
# short-lived container, so its memory peak does not count against the running bot's.
#
#   VOE_SYNC_TARGET=ubuntu@<server> scripts/sync_volyn_queues.sh
#
# Installed as a launchd job by `make install-volyn-sync`.
set -eu
: "${VOE_SYNC_TARGET:?set VOE_SYNC_TARGET=user@server}"
cd "$(dirname "$0")/.."
export_file="$(mktemp "${TMPDIR:-/tmp}/volyn-queues.XXXXXX")"
trap 'rm -f "$export_file"' EXIT

uv run python scripts/export_volyn_queues.py "$export_file"
ssh "$VOE_SYNC_TARGET" \
    'cd ~/lyampochka-bot && docker compose run --rm --no-deps -T bot python -m poweron.import_voe' \
    < "$export_file"

#!/bin/sh
# Weekly Volyn queue sync, run on the owner's Mac (a Ukrainian IP: the server is challenged
# by Cloudflare on energy.volyn.ua). Exports the address → queue table and pipes it into
# the bot, which replaces its catalogue in one transaction.
#
#   VOE_SYNC_TARGET=ubuntu@<server> scripts/sync_volyn_queues.sh
#
# Installed as a launchd job by `make install-volyn-sync`.
set -eu
: "${VOE_SYNC_TARGET:?set VOE_SYNC_TARGET=user@server}"
cd "$(dirname "$0")/.."
export_file="$(mktemp -t volyn-queues).json.gz"
trap 'rm -f "$export_file"' EXIT

uv run python scripts/export_volyn_queues.py "$export_file"
ssh "$VOE_SYNC_TARGET" \
    'cd ~/lyampochka-bot && docker compose exec -T bot python -m poweron import-voe-queues' \
    < "$export_file"

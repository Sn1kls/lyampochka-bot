#!/bin/sh
# Volyn outages sync, run every 15 minutes on the owner's Mac (a Ukrainian IP: the server is
# challenged by Cloudflare on energy.volyn.ua). Exports the outages going on now in the whole
# oblast and pipes them into the running bot container, which swaps its snapshot.
#
#   VOE_SYNC_TARGET=ubuntu@<server> scripts/sync_volyn_outages.sh
#
# Installed with the weekly queue sync by `make install-volyn-sync`, as copies kept out of the
# repo (launchd jobs may not read /Volumes). A failed export sends nothing: the bot keeps the
# last snapshot and stops showing it once it is an hour old.
set -eu
: "${VOE_SYNC_TARGET:?set VOE_SYNC_TARGET=user@server}"
here="$(cd "$(dirname "$0")" && pwd)"
export_file="$(mktemp "${TMPDIR:-/tmp}/volyn-outages.XXXXXX")"
trap 'rm -f "$export_file"' EXIT

date '+%Y-%m-%d %H:%M'
python3 "$here/export_volyn_outages.py" > "$export_file"
ssh -o ConnectTimeout=20 -o BatchMode=yes "$VOE_SYNC_TARGET" \
    'cd ~/lyampochka-bot && docker compose exec -T bot python -m poweron.import_voe_outages' \
    < "$export_file"

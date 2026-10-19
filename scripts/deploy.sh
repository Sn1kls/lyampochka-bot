#!/bin/sh
# Runs on the server after `git pull`, via the deploy key's forced command (README, "Автодеплой").
set -eu
cd "$(dirname "$0")/.."

GIT_SHA=$(git rev-parse --short HEAD) docker compose up -d --build --remove-orphans
# A crash on startup shows up as "restarting", not "running", once the container has had time to fail.
sleep 20
docker compose ps
docker compose ps --status running --services | grep -qx bot
echo "deployed $(git rev-parse --short HEAD)"

# Lyampochka

During scheduled power outages in Ukraine, the question "when will the lights go out today?" comes up several times a day. The answer is on the utility's website, but you have to remember to check it, find your address, and check again when the schedule changes.

Lyampochka ([@lyampochka_bot](https://t.me/lyampochka_bot)) does that for you. You give it your address once, and it:

- shows the outage schedule for that address;
- lets you know when the schedule has been updated;
- reminds you shortly before the power goes off and before it comes back.

Right now it works for the Ternopil region, using data from Ternopiloblenergo. More regions are next (see [Roadmap](#roadmap)).

## How it's built

The Telegram bot is the first client of a small core called `poweron`. The core knows about addresses, schedules and reminders, but nothing about Telegram, HTTP or databases. Everything external plugs in through a few interfaces:

- `ScheduleSource` / `CatalogSource`: where schedules and addresses come from. Today that's the Ternopiloblenergo API (`adapters/toe_api`). Another region means another adapter, with no changes to the core.
- `Repository`: storage (SQLite through async SQLAlchemy).
- `Notifier` and `Clock`: sending messages and telling the time, so the core can be tested without Telegram or a real clock.

`import-linter` checks these boundaries in CI, and `mypy --strict` runs on the core.

**Stack:** Python (asyncio), aiogram 3, httpx, SQLAlchemy 2 (async) + Alembic, SQLite, pydantic, Docker, GitHub Actions, ruff, mypy, import-linter, pytest.

The utility's API is unofficial and can change without warning. When its format changes or it stops responding, the bot sends me an alert in Telegram, at most once an hour per problem.

The database stores people's addresses, so the nightly backup the bot sends me is encrypted (scrypt + Fernet).

Every push to `main` runs the checks and deploys over SSH. The deploy key on the server can only pull `main` and restart the bot.

The worker pings [healthchecks.io](https://healthchecks.io) after every poll. If the server or the worker goes down, the pings stop and healthchecks.io alerts me.

The full spec (in Ukrainian) is in [`docs/SPEC.md`](docs/SPEC.md).

## Run it yourself

You'll need Docker and a bot token from [@BotFather](https://t.me/BotFather) (`/newbot`).

```bash
cp .env.example .env   # fill in BOT_TOKEN, ADMIN_CHAT_ID, CONTACT
make up                # build and start in the background
make logs              # watch what's happening
make down              # stop
```

| Variable | What it's for |
| --- | --- |
| `BOT_TOKEN` | the token from BotFather |
| `ADMIN_CHAT_ID` | your own chat id: alerts and `/status` go here. [@userinfobot](https://t.me/userinfobot) will tell you yours |
| `CONTACT` | your email or @username. It goes into the User-Agent, so the utility can reach you if the bot bothers their API |
| `POLL_INTERVAL_SEC` | how often to check for new schedules, 300 seconds by default |

Everything else in `.env.example` works out of the box. Data lives in the `data` Docker volume, and the bot needs about 200 MB of RAM.

For development:

```bash
uv sync
make check   # format, lint, mypy, layer rules, tests
make run     # bot and worker in one process
```

## Running it on a server

Any always-on VPS works, and no inbound ports are needed because the bot uses long polling. Clone the repo, fill in `.env`, and run `make up`. To update: `git pull && make up` (migrations run on startup).

<details>
<summary>Automatic deploy from GitHub Actions</summary>

After every push to `main`, CI runs `make check` and then the `deploy` job connects over SSH. On the server the deploy key is limited to a single command, so even a leaked key can only deploy what's already in `main`:

```
restrict,command="cd /home/ubuntu/lyampochka-bot && git pull --ff-only -q && exec ./scripts/deploy.sh" ssh-ed25519 AAAA... github-actions-deploy
```

Repository secrets: `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_TARGET` (`ubuntu@<IP>`).
</details>

<details>
<summary>Backups and restoring</summary>

`make backup` writes a consistent copy of the database to `backups/` (even while the bot is running). Backups contain users' addresses, so keep them private.

If `ADMIN_CHAT_ID` and `BACKUP_PASSWORD` are set, the bot also sends an encrypted backup to the admin chat every day around 04:00 Kyiv time. Keep the password in a password manager: without it the backup can't be restored. To restore one:

```bash
uv run python scripts/restore_backup.py poweron-YYYY-MM-DD.sqlite3.enc backups/restored.sqlite3
make down
docker compose run --rm --no-deps -v "$PWD/backups:/backups" bot \
    cp /backups/restored.sqlite3 /data/poweron.sqlite3
make up
```
</details>

<details>
<summary>Admin commands</summary>

`/status` works only from `ADMIN_CHAT_ID`: version, number of users and addresses, queued notifications, and for each outage group when the utility was last polled and which day the latest schedule covers. A ⚠️ shows up only if the bot really can't reach the utility. New users are announced in the same chat ("👤 New user: Name @username"); names aren't stored.
</details>

## Roadmap

- More regions, starting with Volyn. My notes on the Volynoblenergo website are in [`docs/volyn-notes.md`](docs/volyn-notes.md). It has no JSON API, so it will need a different kind of adapter.
- Other regional utilities, each as its own adapter next to `toe_api`.
- More clients for the same core, for example a mobile app on top of an HTTP API.

Ideas and bug reports are welcome in Issues.

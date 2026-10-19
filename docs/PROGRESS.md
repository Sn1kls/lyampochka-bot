# Progress log

Newest entry at the bottom. Each entry: date, phase, done, decisions, open questions, next step.

## 2026-10-17 — setup

- Done: repo harness created (CLAUDE.md, .claude/, Makefile, docs/SPEC.md).
- Decisions: Python 3.14 target, uv, aiogram 3 + APScheduler, long polling.
- Decisions: ports-and-adapters layout (`core` + `adapters`), internal `user_id` with `identities` / `delivery_targets`, outbox for all notifications, SQLAlchemy + Alembic on SQLite (Postgres-ready). Goal: a mobile app can be added later as another adapter.
- Open questions: SPEC §2.3 (slot values, timezone, X-debug-key, rate limits).
- Next step: `/phase 0`.

## 2026-10-17 — phase 0 (API verification)

- Done: `scripts/probe.py` (stdlib only, sequential, 1 req/s) probes catalog + `/a_gpv_g` for Ternopil, vul. Sadova 1 (subqueue 4.1) and saves real responses to `tests/fixtures/`. All SPEC §2.3 points answered in `docs/api-notes.md` (overrides SPEC §2).
- Confirmed: slot semantics from the site client's own legend: `"1"` = OFF, `"10"` = SWITCHING («час на перемикання, можлива відсутність»), `"0"` = ON; 48 half-hour slots keyed by start time, Europe/Kyiv wall clock; `dateGraph` is a calendar date.
- Findings that change the design: `X-debug-key` is mandatory and alone selects the subqueue (`group`/`time` ignored), so polling a subqueue needs one representative address per `cherg_gpv`; per-subqueue caching still holds (`dataJson` has only that subqueue, identical for all its addresses). «Не входить» buildings still get a schedule from `/a_gpv_g`, so decide from `building-names`, like the site. Empty answers: `hydra:member` is `null` or `[]`.
- Cloudflare caches `/a_gpv_g` by URL (`s-maxage=7200`); a request `Cache-Control: no-cache` does not bypass it, a changed query string does. The cache key ignores `X-debug-key`: an early probe request without the key cached `[]` on some edge nodes for the Sadova 1 site URL (expires ~19:43). The probe now sends non-site-like requests only to unique URLs; the client must always send matching `time` + key.
- Decisions: probe stays stdlib-only (no `pyproject` before Phase 1); expected intervals for the 4.1 fixture are pinned in `api-notes.md` for the Phase 1 test.
- Owner decisions (after review): `dateCreate` is shown as is, without time-zone conversion (like the site); the client bypasses the CDN cache by moving `before` a few seconds per poll, only inside `adapters/toe_api`. The owner visually confirmed the 4.1 schedule against the site.
- Not observed yet: a day with two members (tomorrow published), a day without outages, a non-empty planned-works item, `#` suffix in `dataJson` keys.
- Next step: `/phase 1`.

## 2026-10-17 — phase 1 (core)

- Done: `pyproject.toml` (uv, Python 3.14; all later deps checked to install on 3.14: aiogram 3.31, SQLAlchemy 2.1, APScheduler 3.11, aiosqlite, pydantic-settings, alembic), `core/domain` (models, `parse_slots`, `merge`), `core/ports.py` (`ScheduleSource`, `CatalogSource`, `SourceError` → `SourceUnavailable` / `ApiSchemaError`), `adapters/toe_api` (pydantic models + `ToeClient`). 34 tests; `make check` green (ruff, mypy --strict, import-linter, pytest).
- Decisions:
  - `Interval` bounds are aware UTC instants, displayed in Kyiv: Python compares and subtracts same-tzinfo datetimes by wall clock, which breaks on DST days. A day is walked as a real timeline, so DST days are 23/25 h (both transitions tested).
  - Errors live in `core/ports.py` so services can catch them without importing adapters.
  - `ToeClient`: ≤1 req/s under one lock, 3 attempts with backoff + jitter, `Retry-After` capped at 60 s, any `httpx.RequestError` / non-UTF-8 body mapped to `SourceError`.
  - CDN bypass: `before` = tomorrow + current Kyiv time of day (unique for a day; not yet live-checked beyond `T00:MM:SS`).
  - The client returns only `dataJson[requested subqueue]`, keyed by the full trimmed `chergGpv` (`#suffix` kept, like the site); «Не входить» / empty → `None`, no request.
  - Deferred to their phases: `Repository`/`Notifier`/`Clock` ports, diff/events/reminders, `config.py`, `__main__`.
  - Code style (owner): lean code, descriptive English names, minimal comments; recorded in CLAUDE.md.
- Open questions: should bot texts be bilingual (English + Ukrainian)? SPEC lists multilingual as a non-goal (Phase 3).
- Notes for later: `DaySchedule.created_at` must be shown without tz conversion (Phase 3); `DaySchedule` is frozen but holds a dict, so don't hash it (Phase 2 uses `data_hash`); a non-string slot value fails the whole response with `ApiSchemaError`.
- Next step: `/phase 2`.

## 2026-10-17 — phase 2 (storage, polling, outbox)

- Done: SQLAlchemy 2.1 async tables + Alembic initial migration (users, identities, delivery_targets, subscriptions, schedule_versions, outbox), `SqlRepository`; `core/domain/diff.py` (`data_hash`, outage diff with added/removed, structured payload); services `Subscriptions` (register, add, remove), `Polling`, `Notifications`; `worker/runner.py` (poll every `POLL_INTERVAL` ± 20 s, dispatch every 5 s). 52 tests; `make check` green (mypy now on all of `src`, 3 import contracts).
- Done when: `test_new_version_reaches_each_subscriber_exactly_once` — new version → one outbox row per subscriber → dispatch → repeated cycle and restart without duplicates — passes on real SQLite migrated by Alembic.
- Decisions:
  - Plain asyncio loops instead of APScheduler (no extra dependency); the clock is passed as `now` instead of a `Clock` port.
  - Version + its outbox rows are saved in one transaction. An unchanged poll touches `fetched_at`, which gives the last successful poll per subqueue (§9, `/status`).
  - A change is announced only to subscriptions created before the previous poll of that subqueue, so a first load is never an update, even on an abandoned subqueue with stale versions.
  - `dedupe_key` = subscription + day + previous poll time + new hash: a repeated or parallel poll dedupes, a real A→B→A→B flip-back is announced again.
  - Outbox row per subscription; retries with 30 s × 2ⁿ backoff, max 5 attempts, then logged as given up; blocked target → `is_active = false`; channel without a notifier is skipped.
  - `UtcDateTime` column type keeps datetimes aware on SQLite and rejects naive ones; SQLite foreign keys are switched on.
  - Security review (PII now stored): no findings. For Phase 3: refuse rebinding a delivery target to a different user.
- Deferred: schedules service, `config.py`, `__main__`, `catalog_cache` (Phase 3); `resolve_groups` / `cherg_checked_at` (Phase 4); circuit breaker, admin alerts, graceful shutdown (Phase 6).
- Known limits: delivery is at-least-once (a failure on one of several targets resends to all; only one channel exists now); dispatch is N+1 per message (fine at personal scale); a subscriber gets one push per changed day; `run_migrations` must be called before the event loop starts (Phase 3 `__main__`).
- Next step: `/phase 3`.

## 2026-10-17 — phase 3 (Telegram bot)

- Done: `adapters/telegram` (texts, render, keyboards, `/add` FSM wizard, `/start /help /list /schedule /next /remove /forget`, `TelegramNotifier`, command menu, persistent phone keyboard), services `Catalog` (24 h cache in `catalog_cache`, normalised search), `Schedules`, `Subscriptions` (find/register/add/remove/forget), `config.py` (pydantic-settings), `__main__` (`bot | worker | all`), Docker (`Dockerfile`, `compose.yaml`, `make up/logs/down/simulate`), `scripts/simulate_update.py`. ~170 tests; `make check` green.
- Done when: the owner added their address, saw the schedule of both their queues in Telegram, and received the push after `make simulate` (bot running in Docker).
- Work split: contracts first, then Sonnet agents in parallel worktrees (core + telegram), review fixes by agents, integration and verification by me.
- Decisions:
  - Registration only on `/start`; other commands ask for `/start` (respects `/forget`). A delivery target is never rebound to another user.
  - Wizard buttons carry a search generation, so a button from an older list is rejected. Auto-pick happens only on an exact, unique name; a partial single match is still a button.
  - Switching slots: `/next` shows the window (`можуть вимкнути з 10:30, точно — о 11:00`), the day total shows `3 год (до 4 год з перемиканнями)`.
  - Buildings in several subqueues (found during acceptance, see api-notes): queues come from `building-groups`; the user picks which to track at `/add`; pushes and `/next` cover tracked queues; the others stay viewable from `/schedule`. Table `subscription_subqueues(…, notify)`.
  - New subqueues are polled within ~10 s (`poll_new`), an empty one at most every 5 min.
  - Informal "ти" in texts; `dateCreate` shown as is; httpx INFO logs off (URLs carry addresses).
  - Container memory limit 512 MB instead of SPEC's ~256 MB: aiogram alone takes ~120 MB, the bot idles at ~200 MB.
- Owner decision: texts stay Ukrainian only for now; English comes later as a separate step.
- Known limits: a building in two queues costs two API calls per poll (one call returns both); `poll_new` does a few DB reads every 10 s; `building-groups` is not cached.
- Deferred: `/settings`, reminders, `resolve_groups` (Phase 4); circuit breaker, admin alerts, graceful shutdown (Phase 6); FSM state lives in memory, so a restart drops an unfinished `/add`.
- Next step: `/phase 4`.

## 2026-10-17 — phase 4 (reminders, settings, subqueue re-check)

- Done:
  - `Reminders.tick` (every 60 s): "за N хв" reminders before outages and before power returns, for tracked queues only, computed from the latest stored versions. N is the real time left.
  - `Schedules.events`: every event ahead over two days; `/next` uses it.
  - `/settings` and the «⚙️ Налаштування» button: three labelled buttons that cycle — update pushes ✅/🚫, before outage, before power returns (без → 15 → 30 → 60).
  - `SubqueueChecker.check` (hourly over subscriptions not checked for 24 h): one `building-groups` call per building. A changed queue set is replaced atomically together with a «черги змінилися» message.
  - Renderers for the new message kinds. 226 tests; `make check` green.
- Done when: in Docker, the owner set a 60-min reminder; a simulated 22:00 outage produced the update pushes and «⏰ за 33 хв вимкнуть світло (о 22:00)» for both queues, and the real poll then restored the schedule with a push.
- Work split: contracts, then two Sonnet agents in worktrees (core and telegram), four reviews (code, standards, spec, security: no findings), then one agent applied 11 fixes.
- Decisions:
  - The reminder fires inside `[earliest − N, earliest)`, never after the event started. Its dedupe key is `remind:{sub}:{queue}:{earliest}:{kind}`.
  - A block of switching only (no OFF) is a possible outage with no "power returns" event.
  - If a building returns no queues, the stored ones are kept and the user is told once.
  - The `subqueues_changed` dedupe key is subscription + previous>current.
  - New subscriptions are marked as checked at `/add`.
  - Each subscription and each building is isolated, so one failure does not stop the rest.
- Open questions: none.
- Deferred to phase 6: circuit breaker, admin alerts, graceful shutdown, `/status`.
- Next step: phase 5 (planned works, optional) or phase 6 (deploy).

## 2026-10-17 — phase 5 (planned works)

- Done:
  - `ToeClient.planned_works`: paginated, filtered by `datePlanIn[after]`, dates read as Kyiv wall-clock time.
  - `PlannedWorks.check`, hourly: one request per street. It pushes «🛠 Дім: планові роботи 22.08 з 08:30 до 17:30 — Ремонт ПЛ» when the work lists the building, or lists no buildings at all.
  - Renderer and notifier route. 252 tests; `make check` green.
- Not checked live: Ternopil has no future planned works right now (the API has data only up to August). Tests use real recorded items (`pw_accident_planeds_1032_sample.json`).
- Decisions:
  - The dates are Kyiv wall time with a fake `+00:00` label; the site formats them in UTC. An item with a real offset is skipped as a format-change signal.
  - A malformed item is skipped. If no item on a page matches the format, the page raises `ApiSchemaError`.
  - The reason is kept to one line, at most 300 chars.
  - A rescheduled work is announced again: the dedupe key holds its times.
  - Dedupe keys use `Subscription.instance_key` (id + creation time), because SQLite reuses the ids of deleted subscriptions. Reminders use it too.
  - Planned-work pushes follow the same switch as schedule updates; the settings text says so.
  - `normalise` moved to `core/domain/text.py`.
- Known limits: pagination always costs one extra empty-page request; there is a 10-page cap with a warning.
- Next step: `/phase 6`.

## 2026-10-17 — phase 6 (reliability and deploy)

- Done:
  - Circuit breaker in `ToeClient`: 3 consecutive real outages (retries exhausted, network, 429/5xx) pause all calls for 60 s, doubling up to 1 h. A 4xx or a schema error does not count.
  - `Alerts`: admin alerts in Telegram, at most once per hour per kind. `API_SCHEMA` fires immediately; `API_DOWN` fires only when the breaker opens (`SourcePaused`).
  - Graceful shutdown on SIGTERM/SIGINT: the stop is retried until aiogram polling is up, fetching jobs stop between items, dispatch finishes its batch. `stop_grace_period: 90s`.
  - Admin-only `/status`: version, users, addresses, outbox queue, last poll per subqueue with ⚠️ after 3 poll intervals. It is not in the menu.
  - `key=value` logs with an INFO summary per job run and no personal data.
  - README in Ukrainian: BotFather, `.env`, run, VPS deploy, update, backup.
  - `make backup`: consistent SQLite copy via the backup API into `backups/` (mode 700).
  - 282 tests; `make check` green.
- Done when: in Docker, a simulated update, a reminder and an immediate `docker compose restart` gave 6 outbox rows, each sent once. A later restart takes ~1 s ("stop requested" → "Polling stopped" → back up).
- Found on the way: the container was being OOM-killed by the Docker Desktop VM (2.35 GB shared with other projects' containers), not by its own 512 MB limit. The owner raised the VM to 4 GB, and it has been stable since. A dedicated VPS does not have this problem.
- Reviews: code, standards + spec, security (no findings); 8 fixes applied.
- Decisions:
  - Admin alerts go straight to the admin chat, not through the outbox: the admin is not a subscriber, and the rate limit is in memory.
  - `/status` "last poll" = the newest stored version time.
- Known limits:
  - A stuck retrying call can still outlast the grace period.
  - Alert state resets on restart.
  - Backups are not encrypted.
  - `/status` works in the admin's private chat only.
- Open: permanent hosting. Recommended: Hetzner CAX11/CX22. First check from the server that the toe API answers a foreign IP (`curl` or `scripts/probe.py`).
- Next step: move to a VPS once the owner has one. All SPEC phases (0–6) are done.

## 2026-10-18: deploy and Volyn research

- Deployed: the bot runs from `main` on an Oracle Cloud Always Free VM (Stockholm).
  - Machine: E2.1.Micro, 1 GB RAM + 2 GB swap. A1.Flex was out of capacity.
  - The toe API answers the foreign IP.
  - The SQLite DB was moved from the Mac with no lost or duplicate pushes.
  - Updates: release PR `develop` → `main`, then `git pull && docker compose up -d --build` on the server.
- Bot profile set in BotFather: name «Лямпочка», descriptions, avatar.
- Researched Volynoblenergo. It has an HTML form with free-text search and no JSON API; see `docs/volyn-notes.md`. Postponed by the owner.
- Open: upgrade the Oracle account to Pay As You Go once the button is enabled, so the idle VM isn't reclaimed.

## 2026-10-18: operations

- Container logs are capped at 3 × 10 MB (`compose.yaml`).
- Admin alert on every new user's first `/start`: «👤 Новий користувач: Ім'я @username».
  - The name goes only into that message, never into the DB or logs.
  - `register_user` now returns `(user_id, created)`, so the check is atomic.
  - `Alerts.send` sends without the hourly throttle; error alerts still go through `report`.
- Auto-deploy: after a green `make check` on `main`, the CI `deploy` job SSHes to the server.
  - The deploy key is limited by a forced command to `git pull --ff-only && ./scripts/deploy.sh`.
  - `deploy.sh` fails unless the bot is running 20 s after `compose up`.
  - Secrets: `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS`, `DEPLOY_TARGET`.
  - The first run (release #13) passed after a rerun; two secrets had been missing.
- Open: Oracle Pay As You Go upgrade (the button is still disabled); Volynoblenergo is postponed.

## 2026-10-18: buttons instead of commands

- Texts no longer send users to `/add`, `/help`, `/schedule` or `/settings`.
  - Inline «➕ Додати адресу» appears under the greeting (when there are no addresses) and under «Адрес ще немає».
  - «Мої адреси» carries add and remove buttons.
  - The `Action` callback reuses the existing flows and leaves an open wizard.
- The reply keyboard is down to four buttons. The old labels still work until a client receives the new keyboard (next `/start` or add/remove).
- Removing an address now needs a confirmation, so an old list button can't delete anything by itself.
- Decision: stay on SQLite. Postgres comes when a second independent DB writer appears (a separate API process, a split worker, or another service). A C# client would go through the HTTP API, not the DB.
- Menu announcement:
  - `make announce-menu VERSION=N` queues «🔄 Оновив меню» with the new reply keyboard for every user with an active Telegram target, once per version, through the outbox.
  - It prints how many messages were queued, so a forgotten version bump shows 0.
  - Run it once after each reply-keyboard change. Version 2 is the four-button menu.

## 2026-10-18: monitoring and backups

- Heartbeat: with `HEALTHCHECK_URL` set, the worker pings healthchecks.io after every finished poll. If the server, the container or the worker dies, the outside monitor alerts the owner. Ping errors are logged by type only (the URL is a secret) and never raise.
- Daily backup: with `ADMIN_CHAT_ID` and `BACKUP_PASSWORD` set, the worker snapshots SQLite during 04:00 Kyiv and sends `poweron-YYYY-MM-DD.sqlite3.enc` to the admin chat.
  - The snapshot uses SQLite's backup API, in memory, with no plaintext on disk.
  - The file is encrypted with scrypt (n=2^16) + Fernet.
  - A failure alerts the admin (`BACKUP_FAILED`, at most hourly) and is retried within the hour.
  - `scripts/restore_backup.py` decrypts the file, checks its integrity and writes it with mode 0600, never overwriting.
- Decisions:
  - The heartbeat means "the worker runs", not "the API answers". API trouble already has its own alerts.
  - Backups are SQLite-only; with another database they are switched off with a log line.
- Reviews: simplify, code-review, security-review (no findings).

## 2026-10-19: real poll times in /status

- Bug: `/status` showed ⚠️ for every subqueue and «ще не опитувалась» for a new one, although the worker polled every 5 minutes.
  - "Last poll" was the newest stored schedule version (phase 6 decision).
  - Since 18.10 Ternopiloblenergo publishes no schedules for our queues, so nothing new was stored.
- Fix: a successful fetch, with or without schedules, records its time in the new `subqueue_polls` table (migration `3a7c1e9d5b20`).
  - `/status` shows the poll time and the newest schedule day: «4.1: опитано 19.10 22:45, останній графік на 17.10» or «графіків ще немає».
  - ⚠️ now means the bot really stopped reaching the source: no successful poll for 3 intervals. A failed fetch is not a poll.
- The poll time is recorded after the schedules are stored, so a poll that crashes while saving still shows ⚠️.
- Also fixed (found by code review):
  - Before, a user who subscribed while the source published nothing got no push when schedules came back: the first schedule counted as their "first load".
  - Push recipients are now everyone subscribed before the previous successful poll, even an empty one.
  - Test: `test_a_subscriber_who_joined_while_the_source_was_empty_gets_the_first_schedule`.
- `Repository.last_polled_at` is renamed to `last_version_at`. Only `poll_new` uses it now, to retry subqueues that have no versions yet.
- Backups after the first night:
  - one test backup was sent by hand on 18.10;
  - the first automatic one came on 19.10 at 04:03 Kyiv;
  - from now on, one a night between 04:00 and ~04:10.

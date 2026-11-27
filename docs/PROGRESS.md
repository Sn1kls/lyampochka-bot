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

## 2026-10-19: versioning

- Version 0.2.0 (was 0.1.0 since phase 1). `/status` shows `0.2.0 (<commit>)`: `deploy.sh` passes `git rev-parse --short HEAD` as the `GIT_SHA` build arg. A local `make up` shows `dev`.
- Release process (SemVer, 0.x while the bot is personal):
  - minor (0.3.0) for a release with features, patch (0.2.1) for fixes only;
  - the bump commit goes into `develop` before the release PR;
  - after the deploy, tag `vX.Y.Z` on `main` and create a GitHub Release whose notes list the merged PRs.

## 2026-11-08: Volyn, second look

- Reopened Volynoblenergo: the owner now lives in Ківерці and wants the whole oblast. Full findings and the agreed plan are in `docs/volyn-notes.md`.
- Found:
  - the queue lookup (`cherga/`) gives `6.1`-style subqueues per address;
  - the schedule search needs a fresh PHP session per search;
  - the inneti API behind the archive has no schedule data (PNG images only);
  - no outages were scheduled in Volyn, so the schedule result format is still unseen.
- Added `scripts/probe_volyn.py` and `tests/fixtures/voe_*.html`.
- **Blocked:** from the production server energy.volyn.ua answers a Cloudflare challenge (403). We don't get around it. The owner has to choose: ask Volynoblenergo for access, fetch from a device in Ukraine, or move hosting.

## 2026-11-08: Volyn region

- Done: Volynoblenergo schedules for the whole oblast. Details in `docs/volyn-notes.md` ("How it is built", "Weekly catalogue").
  - Schedules come from the inneti archive PNGs and are decoded from pixels on the server (stdlib PNG reader, no AI). The server is not challenged there.
  - The address → queue table comes from energy.volyn.ua. Cloudflare challenges the server there, so the owner's Mac exports it weekly via launchd and pipes it into `python -m poweron.import_voe`, run in a short-lived container.
  - `/add` starts with a region choice.
  - Subqueue keys are namespaced (`voe:6.1`), so only the new `voe_buildings` table needed a migration.
- Work split: the image adapter was built by a Sonnet agent in a worktree; core, DB, import, bot and wiring by me.
- Decisions:
  - Pixels instead of a vision LLM: the image is machine-drawn with two exact colours. Pixels are deterministic, free and need no prompt-injection review.
  - Pure-stdlib PNG decoding instead of Pillow: ~1.3 s per new revision, in a thread.
  - A subscription's region is derived from its queue prefix; no `provider` column.
  - Catalogue ids are crc32 of the names, stable across imports.
- Known limits:
  - The Volyn image has no "switching" state.
  - Volyn has no planned-works feed.
  - The catalogue is only as fresh as the last Mac sync; there is an alert after 10 days.
  - The DB is ~29 MB bigger, which matters for the 50 MB Telegram backup limit.
- After deploy: run `make sync-volyn TARGET=…` once, then `make install-volyn-sync TARGET=…`.

## 2026-11-08: Sentry

- Done: optional error reports to Sentry (`SENTRY_DSN`, `SENTRY_ENVIRONMENT`), in `src/poweron/observability.py`, started by both entry points (`__main__`, `import_voe`).
  - `logger.exception(...)` and uncaught exceptions become events; the release is `poweron@<version>+<git sha>`.
- Privacy decisions:
  - Handlers hold addresses in local variables, so `include_local_variables=False`.
  - Toe API URLs carry the address and aiogram's Telegram URLs carry the bot token, so `auto_enabling_integrations=False`: no httpx, aiohttp or SQLAlchemy breadcrumbs. The default integrations stay: logging, excepthook, dedupe.
  - `before_send` replaces the bot token (and its secret half) in every string of an event, keeping the other types.
  - Found by the security review: SQLAlchemy errors listed the row values (addresses, chat ids), and they reached the logs too. The engine now uses `hide_parameters=True`.
  - `ApiSchemaError.from_validation` keeps only field paths and reasons, raised `from None`: pydantic's text and a chained ValidationError carry the API's input values.
  - `import_voe` logs a refused import as an error, so Sentry reports it.
  - `send_default_pii` is left at its default (off); setting it explicitly is deprecated in sentry-sdk 2.74.
- Test: one event from a logged exception has no local variables, no address, no API URL and no token, and its only breadcrumb is our own log. Turning off any of the three guards makes it fail (checked).
- Owner's access: the official Sentry MCP server (`claude mcp add --transport http sentry https://mcp.sentry.dev/mcp/<org>/<project>`, OAuth).

## 2026-11-20: Feedback to the developer

- Done: `/feedback` and a third menu row «❓ Допомога | ✉️ Відгук».
  - The user sends one message of any kind, or one album (its parts are collected for 1 s, since they arrive as concurrent updates).
  - The admin chat gets a `copyMessages` copy, then a header «✉️ Відгук · користувач #id» with the name and addresses. Nothing is downloaded.
  - The admin's Reply to the header or to a copy goes back through the outbox (`feedback_reply`, deduplicated by the admin's message id). Replies longer than 4000 characters or not text are refused; a reply to a forgotten user says so.
  - Messages Telegram cannot copy (polls, dice) are refused and not counted; parts that come after their album was sent are dropped.
  - The reply is a Telegram Reply to the user's own feedback message (`feedback_messages.source_message_id`), so they see what it answers; it still arrives if they deleted that message.
  - The user's Reply to a «💬 Відповідь розробника» is a new feedback (same limit), so the conversation goes on without pressing «✉️ Відгук». Its header in the admin chat is a Telegram Reply to the admin's answer it continues.
  - For that, `Notifier.send` returns a ref of the delivered message, and `Notifications` stores each delivered answer in `feedback_messages` with the admin's message as `source_message_id`. The Reply is matched by that row, not by text.
- Decisions:
  - Core `Feedback` service owns the rate limit (5 per hour per user, in memory, reset by a restart) and the reply queueing; the channel keeps the content.
  - Found by the security review: the first version took the author from «#id» in the replied message's text, and a copy of a user's own text could forge it. Table `feedback_messages` now maps each admin-side message (header and copies) to its author, and only those messages count as feedback. `/forget` sets `user_id` to NULL, so the admin learns the user is gone.
  - The feedback content lives only in the admin chat; `/forget` cannot reach it, and the prompt says the developer reads it.
  - The limit is checked when `/feedback` is pressed, so a long text is not written in vain.
  - The menu update (`MENU_UPDATED`) is now sent with `disable_notification`, and its text names the two new buttons.
- After deploy: `make announce-menu VERSION=N` with N above the last one used.

## 2026-11-21: Stale reminder warning

- Bug report: a "power goes off in 30 min" reminder, then minutes later an update that removed that outage. Production data (`voe:4.1`) showed a race, not a stale cache: the 17:00 reminder went out at 17:00:18, the oblenergo published the new image at 17:02:17, the poll saw it at 17:07. Same at 05:30/05:57.
- Done: a schedule update now carries `stale_reminders` (ISO starts) per subscription: future outage starts the user was already reminded about (`REMINDER_OFF` dedupe key in the outbox) that no current outage starts at. Telegram renders «⚠️ Нагадування про вимкнення о HH:MM уже неактуальне.» under the title.
- Decisions:
  - Re-fetching the schedule right before a reminder was dropped: it would not have helped either reported case.
  - A queued reminder counts as reminded (it is dispatched before the update); one waiting for a retry may arrive after the warning.
  - Not covered: `REMINDER_ON` (off by default), users with `notify_on_update` off.

## 2026-11-21: Per-queue tracking in settings

- Done: the settings of an address in several queues get one button per queue («✅ Черга 2.2» / «🚫 Черга 2.2»), sorted by name so they stay in place. A press stops or resumes pushes and reminders for that queue; its schedule stays viewable.
  - `Subscriptions.set_tracked` + `Repository.set_queue_tracked`, one row per press.
  - The last tracked queue cannot be turned off (alert «Хоча б за однією чергою треба стежити…»). The guard is in the UPDATE itself, so two quick taps on two settings messages cannot untrack both.
  - The callback carries the plain subqueue, since a scoped one holds the ":" separator.
- Known limits:
  - The guard is atomic under SQLite's single writer; Postgres will need a row lock (marked `ponytail:`).
  - A press that lands while the catalog re-check rewrites the building's queues can be undone by it; the user then gets the «змінилися черги» message listing what is tracked.

## 2026-11-22: Shorter pushes, battery reminders, reminder mode

- Done (the owner's request):
  - A schedule push starts with «💡 Оновлення на сьогодні (22.11):» or «на завтра (23.11)», then the whole day. The «Гірше / Краще / Змінили» headline is gone, and a day without outages shows «🟢 00:00–24:00».
  - «Сьогодні / завтра» is decided when the message is sent, so `render_update` takes `now`.
  - Reminders: 🪫 before power goes off, 🔋 before it comes back, in the settings too.
  - The address name is shown only to users with several addresses: both kinds of payload carry `address_count`. The queue is still named when the address tracks several. Messages queued before this change have no `address_count` and still name the address.
  - Setting `remind_exact` (per address, Ternopil only, since Volyn has no switching): count reminders down to the sure 🔴 or 🟢 instead of the start of 🟡. An outage that is only 🟡 is not reminded in this mode.
- Decisions:
  - Exact events are computed separately (`queue_events(..., exact=True)`, domain `sure()`): switching keeps the state before it. Shrinking the possible event to its `latest` did not work: once 🟡 starts, the possible scan sees the outage as already begun and drops the 🔴 event, so a 30-minute reminder before 🔴 could never fire.
  - An exact reminder's payload has `earliest == latest`, so it renders as «ВИМКНУТЬ світло (о HH:MM)». Its dedupe key uses that moment, so the stale-reminder warning names the right time.
  - Found by the code review: for exact subscribers the stale-reminder check compares sure-OFF starts (`moved_starts(now, exact=True)`). Otherwise a 🔴 that became 🟡 while a 🟡 at the same minute became 🔴 kept every start and was not flagged.
  - `address_count` of an update is counted once per poll, from the `all_subscriptions()` the poll already loads (found by the review bot).
- Known limits:
  - The push preview no longer tells whether things got better or worse (the owner's choice).
  - Switching the mode right before an outage can bring a second reminder for it: the dedupe key holds the start of 🟡 in one mode and of 🔴 in the other.
  - A 🟡 right after midnight does not see yesterday's 🔴, so no exact «ДАДУТЬ» reminder for it (pre-existing for the possible mode too).
  - `remind_exact` sent for a Volyn address by a forged callback is stored and hidden; it changes nothing there.

## 2026-11-23: Exact mode for outages only

- Done (the owner's request): `remind_exact` now changes only 🪫 reminders. A 🔋 reminder always counts down to the start of 🟡 and shows both times («з 12:30, точно – о 13:00»).
- Why: on 23.11 on 4.1, power came back at 12:30, as 🟡 started. The exact reminder came at 12:45, after the power was already back. The setting is labelled «до точного відключення» anyway.
- Known limit: a 🔋 reminder sent in the old exact way just before the deploy can be followed by one more in the new way for the same return (different dedupe key).
- Known limit: a 🟡 published after it has already started gets no 🔋 reminder, in either mode, since power may come back any minute.

## 2026-11-23: Rename an address

- Done (the owner's request): «✏️ Змінити назву» in an address's settings asks for a new name; the next text message becomes the label (trimmed, cut to 40 characters like in `/add`). `Subscriptions.rename` in core, no migration: `label` already existed.
- Leaving: «Скасувати» (back to the settings), any menu button. A command does not leave it, like the feedback dialogue. A photo, a sticker or an invisible name gets the question again.
- Known limit: outbox rows already queued keep the old label (it is copied into the payload), so one push may still carry the old name.

## 2026-11-23: Lviv research

- Researched Lvivoblenergo for a third region; details in `docs/lviv-notes.md`.
- Found:
  - schedules are text per group (`Група 1.1. Електроенергії немає з 16:30 до 20:00.`) in two CMS items, «Today» and «Tomorrow», 3 KB each; only OFF and ON, no switching;
  - the address → queue lookup is a public inneti API (`pw_cities`, `pw_streets`, `pw_accounts`), one row per consumer account, so a building can show «Не входить» next to a queue, or two queues;
  - everything answers the production server (200), so no Mac export like Volyn.
- Added `scripts/probe_lviv.py` and fixtures `tests/fixtures/loe_*.json` (one public address, no account numbers).
- Open: when «Tomorrow» is filled and how both items change at midnight.
- Next step: grill the open design points, then a plan for `feature/lviv-oblast`.

## 2026-11-23: Lviv region

- Done: Lvivoblenergo schedules for the whole oblast; details in `docs/lviv-notes.md` ("How it is built").
  - `adapters/loe_api`: the schedule text is parsed per group; the catalogue is read live from the inneti API. Everything answers the production server, so no Mac export.
  - `/add` offers «Львівська» as a third region; keys are `loe:3.1`, so no migration.
  - The pacing/retry loop of `VoeClient` moved to `adapters/paced_http.py` and is shared by both clients.
- Decisions (owner): catalogue live with the usual 24 h cache; «Не входить» next to a queue counts as the queue, two queues are offered for picking; the hromada is shown next to the settlement; no planned works for now.
- Checked live: today's text and пл. Ринок (3 → 3.1, 9 → 3.1 + 4.1) through the real client.
- Known limits: when «Tomorrow» fills up and what both items do at midnight is still unobserved; the parser relies on the day in the text either way. Messy street names are shown as the oblenergo writes them.

## 2026-11-24: Circuit breaker per endpoint

- Bug (production, 10:23): `pw_accident_planeds` answered HTTP 500 for two streets in a row. The one shared `ToeClient` breaker opened and also skipped the schedule poll (`a_gpv_g` was healthy), and the admin got «Сайт обленерго давно не відповідає», which was false.
- Fixed: `ToeClient` keeps a breaker per request path, so a broken endpoint pauses only itself. The 1 request/second pacing stays shared, since it is per host.
- Alerts: a pause in planned works or the subqueue re-check is `SIDE_API_DOWN` («Частина сайту обленерго не відповідає»), rate-limited apart from `API_DOWN`, which now means schedule polling only.
- Accepted: in a full outage each endpoint fails 3 times on its own before it pauses (about 9 requests each instead of one shared stop), and the admin gets both alerts. A 429 also pauses only its endpoint.
- Known limit: a schema error in a side job still reports `API_SCHEMA`, whose text says schedules come from memory.

## 2026-11-26: Emergency outages in Ternopil

- Done: «Що далі» and today's «Графік» start with «⚠️ Зараз аварійне відключення, світло обіцяють дати …» when the oblenergo lists an emergency outage on the user's building (or the whole street). Ternopil only.
  - `ToeClient.emergency_outages` reads `/pw_accidents` with the site's realtime filter; items reuse the planned-works parser and `PlannedWork`.
  - `core/services/emergency.py`: asked by the bot while the user waits, 5 min cache per street, 3 s timeout; a slow or broken API just drops the line, and the failure is remembered for 1 min (the timeout cuts the client's retries short, so its breaker never opens for this endpoint). An outage counts only between its start and planned end.
  - `PlannedWork.affects` replaces `planned_works._affects`, shared by both services.
- Research first: a day of observation (`docs/api-notes.md`, "Current outages"). Rows stay open for days after their planned end, so only rows whose planned end is ahead are shown. No pushes: the API can lag ~5 h, and ids change on every request.
- Decisions (owner): on demand only, exact building match, Ternopil only; the «⚡ Немає світла? Аварійні» button stays.
- Known limits: in `all` mode the bot shares the 1 request/second lock with the worker, so during a poll burst the request may time out and the line is missing. One page of 30 rows per street.
- Volyn rechecked: still behind Cloudflare for the server, inneti tables still empty.

## 2026-11-26: Volyn current outages page

- Researched energy.volyn.ua's current outages page from the owner's Mac; details in `docs/volyn-notes.md` ("Current outages page").
  - A plain form POST, no session; the settlement field matches a substring and the answer is not capped, so a few requests cover the whole oblast.
  - Rows are per street with a building list, type (emergency, planned, schedule applied), reason, start and expected end. Refreshed every 30 min.
- `scripts/probe_volyn.py outages <dir> <settlement>...` saves the raw page; fixtures `voe_outages_lutsk.html`, `voe_outages_none.html`.
- Server access, rechecked: the server is challenged even on `robots.txt`; a German VPN exit is challenged too. Whether a Ukrainian data-centre IP passes is open.
- A real headless browser on the server does not pass either: Cloudflare holds it on a Turnstile challenge. We stop there (no stealth, no captcha solvers).
- Open: a day of observation (how long rows stay after their end), and how the server gets to the page at all.

## 2026-11-26: Current outages in Volyn and planned works now

- Done (the owner's request): «Що далі» and today's «Графік» start with the outage going on now on the user's building, emergency or planned; an emergency wins.
  - «⚠️ Зараз аварійне відключення …» as before, and «🛠 Зараз планове відключення, світло обіцяють дати …».
  - Ternopil: planned works now come from the same `planned_works` request as the pushes (it filters on the planned end, so a started work is returned). It is asked only when there is no emergency.
  - Volyn: the owner's Mac exports the whole oblast's outages every 15 minutes and pipes them into the running bot container (`docs/volyn-notes.md`, "Outages snapshot"). A snapshot older than an hour is ignored.
- `EmergencyOutages` became `CurrentOutages` with a source per region (`CurrentOutageSource` = emergency + planned).
- Why the Mac: the server is challenged by Cloudflare on energy.volyn.ua, even a real headless browser (Turnstile). We do not get around it; the formal request to Volynoblenergo is still the way to drop the Mac.
- Known limits:
  - Volyn depends on the Mac being awake and online; asleep for over an hour means no line (the link button stays).
  - In Ternopil a user may wait for two API requests (emergency, then planned); during a poll burst one may time out and the line is missing.
  - Volyn rows carry the site's reason text as is («Планові ремонтні роботи»).

## 2026-11-27: Reminder for users without an address

- Five users had been in the bot 4–14 days without an address, so they never got a schedule or a push.
- `make nudge-no-address` queues «👋 Адреси ще немає…» once ever per user (`no-address:{user_id}`) for everyone reachable on Telegram with no subscription now who joined over a day ago (someone who removed their only address counts too: removal leaves no trace; none of the first five ever had one); it buzzes, unlike the menu news.
- The text avoids the past tense so it does not guess the user's gender.
- Manual for now; an automatic reminder a day after joining waits until the manual one proves too little.

## 2026-11-27: Dnipropetrovsk research

- Several users asked for Dnipropetrovsk oblast. Researched it for a fourth region; details in `docs/dnipro-notes.md`.
- Found:
  - two operators, DTEK DnEM (18 groups `1.1` … `18.1`) and CEK (12 groups `1.1` … `6.2`), both in one public YASNO JSON API (`app.yasno.ua`): schedules as minute intervals per group for today and tomorrow, and the address → group lookup;
  - the catalogue is search-only (at least 3 letters, at most 20 results), and the operators overlap in Dnipro, Kryvyi Rih and a few other towns, so the bot must search both;
  - dtek-dnem.com.ua challenges even the Mac with Incapsula; CEK's own schedule form was stale on 27.11.
- Added `scripts/probe_dnipro.py` and fixtures `tests/fixtures/yasno_*.json` (public streets only).
- Open, and blocking: whether the production server gets JSON from `app.yasno.ua`, which is behind Incapsula too.
- Next step: the server check, then grill the design points in the notes, then a plan for `feature/dnipro-oblast`. The owner asked for the region buttons in alphabetical order in the same feature.

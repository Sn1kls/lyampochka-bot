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

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

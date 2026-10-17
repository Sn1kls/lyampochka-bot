# poweron

Power outage schedules (ГПВ) for Ternopiloblenergo. The product is the `core`; the Telegram bot is only its first client.
A mobile app (via an HTTP API) comes later and must plug in as another adapter without touching `core` or migrating data.
Personal use for now.

Product name: «Лямпочка» (Telegram `@lyampochka_bot`). Use the brand only in user-facing texts and config, never in package, module or table names (the package stays `poweron`).
The full spec is `docs/SPEC.md`; it is the source of truth. Progress log is `docs/PROGRESS.md`.

Talk to the owner in Ukrainian. Code, identifiers, commits and docs inside the code: English.
User-facing bot texts: Ukrainian, all in `src/poweron/adapters/telegram/texts.py`.

## Workflow

- Work one phase at a time (SPEC §12), via `/phase N`. Do not start the next phase on your own.
- At the start of a session read `docs/PROGRESS.md` first, then only the SPEC sections the phase needs.
- `docs/api-notes.md` (written in Phase 0) overrides SPEC §2 wherever they differ.
- Never guess the unofficial API: anything still open in SPEC §2.3 is a stop-and-ask, not an assumption.
- Do not hit the live API from tests. Live calls only from `scripts/probe.py`, max 1 request/second.

## Commands

```bash
uv sync                      # install deps
make check                   # format check + lint + mypy + import-linter + tests — green before a commit
make test                    # pytest only
make fmt                     # ruff format + ruff check --fix
uv run python -m poweron all # bot + worker in one process (needs .env); also `bot` / `worker`
uv run alembic upgrade head  # apply DB migrations
uv run python scripts/probe.py  # Phase 0 live API probe
```

Package manager is uv only, never pip. Python 3.14 (fallback 3.13, see SPEC §10).

## Architecture rules

Ports and adapters (SPEC §3). Package root `src/poweron/`.

- `core/` (domain + services + ports) imports only stdlib and pydantic. Never aiogram, httpx, SQLAlchemy, or anything in `adapters/`.
- Client adapters (`adapters/telegram`, later `adapters/http_api`) call only `core.services`. Never the repository or the toe API directly.
- Services take and return domain models and the internal `user_id`. Never `chat_id`, never aiogram objects.
- `core` emits structured events into the `outbox`; channel notifiers render them. No human-readable text in `core`.
- `adapters/toe_api` is the only place that knows URLs, headers and raw JSON; validate everything with pydantic, raise `ApiSchemaError` on mismatch.
- DB: SQLAlchemy 2.0 async + Alembic, portable SQL only (SQLite now, Postgres later by `DATABASE_URL`). Every schema change is a migration.
- Roles `bot` and `worker` talk to each other only through the DB, never through in-memory calls.
- Times: store UTC, display Europe/Kyiv. Use `zoneinfo`, never naive datetimes.
- Schedule cache is keyed by subqueue (`cherg_gpv`), never by user.
- Do not build the HTTP API or mobile pieces until the owner asks; just don't block them.

## Git

- Remote: `github.com/Sn1kls/lyampochka-bot` (private). Work through pull requests; the owner reviews and merges.
- Each phase on its own branch `phase-N` from an up-to-date `main`. Commit at the end with Conventional Commits (`feat(phase2): ...`), show `git status` first.
- Push only the phase branch (`git push -u origin phase-N`) and open a PR with `gh pr create`. Never push to `main`, never merge PRs yourself.
- Never force-push, never rewrite history without an explicit request.
- Never commit `.env`, `data/`, or recorded fixtures containing personal addresses.

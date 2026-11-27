# Architecture map

The current shape of the code, for an agent starting a session. Rules live in `CLAUDE.md`, the product in `docs/SPEC.md`, the history and the reasons behind decisions in `docs/PROGRESS.md`. Update this file in the same PR when a flow, a module or a region changes.

## What it does

Users add an address. Each address maps to one or more **subqueues** (`4.1`). The worker polls each subqueue's schedule, stores a new **version** when it changes, and queues pushes and reminders in the **outbox**. The Telegram notifier sends them. Regions: Ternopil (`toe`), Volyn (`voe`), Lviv (`loe`), Dnipropetrovsk (two operators, `dnem` and `cek`, behind one region `dnipro`).

## Flow

```
oblenergo ──fetch──▶ Polling ──version + outbox rows (one transaction)──▶ SQLite
                                                                           │
   Reminders.tick / SubqueueChecker / PlannedWorks ──outbox rows──────────▶│
                                                                           ▼
                        Notifications.dispatch ──▶ TelegramNotifier ──▶ user
```

- `bot` and `worker` are separate roles (`python -m poweron bot|worker|all`), sharing only the DB.
- Worker jobs and their intervals: `src/poweron/worker/runner.py`. Every job is one `repeat(...)` loop; a failure is logged and the loop goes on.
- All wiring (which client serves which region, which service gets which port): `src/poweron/__main__.py`.

## Modules

| Where | What |
|---|---|
| `core/domain/` | pure logic: `models.py` (dataclasses), `schedule.py` (slots → UTC intervals, DST-safe), `diff.py` (change between versions), `providers.py` (region keys) |
| `core/ports.py` | every Protocol (`ScheduleSource`, `CatalogSource`, `Repository`, `Notifier`, …) and the `SourceError` family |
| `core/services/` | one class per job: `polling`, `reminders`, `groups` (`SubqueueChecker`, daily queue re-check), `planned_works`, `current_outages` (the emergency or planned outage on the user's building now, asked live by the bot; an emergency wins), `notifications` (outbox dispatch), `subscriptions`, `catalog`, `schedules`, `feedback`, `status`, `alerts`, `backups` |
| `adapters/toe_api/` | Ternopil JSON API: schedules, catalogue, planned works, emergency outages, a circuit breaker per endpoint |
| `adapters/voe_api/` | Volyn: archive PNGs decoded from pixels (`image.py`) |
| `adapters/loe_api/` | Lviv: schedule text per group (`schedule.py`) and the catalogue, both live from the oblenergo's APIs |
| `adapters/yasno_api/` | Dnipropetrovsk: both operators' schedules and the search-only catalogue from YASNO's JSON API (`client.py`) |
| `adapters/paced_http.py` | shared by `voe_api`, `loe_api` and `yasno_api`: GETs at most once a second, with retries |
| `adapters/db/` | `tables.py`, `repository.py` (`SqlRepository`), `voe_catalog.py` (Volyn `CatalogSource` over the imported table), `voe_outages.py` (Volyn outages snapshot from the Mac), Alembic `migrations/` |
| `adapters/telegram/` | `handlers.py` (commands, FSM for the `/add` wizard, rename and feedback), `render.py` (payload → HTML), `keyboards.py`, `texts.py` (all Ukrainian), `notifier.py` |
| `import_voe.py` | CLI that loads the weekly Volyn address → queue export |
| `import_voe_outages.py` | CLI that swaps the Volyn outages snapshot, piped from the Mac every 15 min into the running bot container |
| `scripts/` | live probes (`probe*.py`), Volyn export/sync, deploy, simulate, restore |

Import-linter (`pyproject.toml`) enforces it: `core` sees only stdlib and pydantic, and adapters never import each other.

## Invariants that are easy to break

- **Subqueue keys** carry the provider: Ternopil keys are plain (`4.1`), others are prefixed (`voe:6.1`). Use `provider_of`, `plain_subqueue`, `scoped_subqueue` from `providers.py`. A subscription's provider is the prefix of its first queue; there is no `provider` column.
- **Provider vs region**: Dnipropetrovsk has two providers (`dnem`, `cek`: their group names collide) under one region `dnipro` (the button and the catalogue). `region_of` maps a provider to its region; the other regions are their own provider. `REGIONS` in `render.py` is keyed by region, in alphabetical order.
- **Slots**: a `DaySchedule` holds 48 half-hour slots keyed by Kyiv start time (`"00:00"`, `"00:30"`, …) with toe's raw codes: `"1"` OFF, `"0"` ON, `"10"` switching. Every source converts into this shape, and `parse_slots` turns it into intervals.
- **Dedupe keys** use `Subscription.instance_key` (id + creation time), since SQLite reuses deleted ids. A changed key format resends or swallows pushes.
- **Recipients of a change** are subscriptions created before the previous successful poll, so a first load is never pushed as an update.
- **A dead schedule source** alerts the admin two ways: toe's circuit breaker (`API_DOWN`), and for every region `Polling`'s `stale_after` (`SCHEDULE_STALE`: a subqueue failing for 3 poll intervals, the limit `/status` uses, counted from the later of its last poll and its oldest current subscription). Separate kinds, so one does not rate-limit the other. A new region gets the second for free.
- **The admin's Reply** finds its user through `feedback_messages` (ref of an admin-side message → user), never through message text. A feedback copy and its header are such messages, and so is the new-user alert: answering it is how the admin writes first. Any message outside a wizard (outside the admin chat) is feedback too: `feedback_without_asking`, the last handler, so it only gets what no other handler took. A reply-keyboard label that changes keeps its old text in `MENU_LABELS` and its handler, since old keyboards stay on phones.
- `core` emits structured payloads; the text is chosen in `render.py`. Old payloads may still sit in the outbox, so a new payload field needs a default when rendered.
- Bot texts are informal «ти», with en dashes in time ranges.

## Adding a region

Worked examples: Volyn (`docs/volyn-notes.md`; imported catalogue, image schedules), Lviv (`docs/lviv-notes.md`; everything live, the closest to a plain new region) and Dnipropetrovsk (`docs/dnipro-notes.md`; two operators in one region, a search-only catalogue).

1. **Research first**: `docs/<region>-notes.md` and a stdlib probe `scripts/probe_<region>.py` (1 request/s, public street names only), with fixtures under `tests/fixtures/`. Find the schedule source, the address → queue source, and whether **the production server** gets an answer (`curl` over ssh). energy.volyn.ua challenges the server with Cloudflare; we never get around such a challenge.
2. `core/domain/providers.py`: a region constant.
3. Adapter `adapters/<region>_api/` implementing `ScheduleSource`. Add it to the independence contract in `pyproject.toml`.
4. A `CatalogSource`: either the region's API (like toe) or an imported table (like Volyn: table + migration, `adapters/db/<region>_catalog.py`, an import CLI, a staleness alert like `VoeCatalogAge`, its own `cache_prefix`). A source that can only search (like YASNO) is a `SearchCatalogSource`: `/add` then asks for the house number as text.
5. `__main__.py`: add the region to `Catalog` (bot, keyed by region), `SchedulesByProvider` and `SubqueueChecker` (worker, keyed by provider).
6. Telegram: `REGIONS`, `_site` and `outages_url` (the page of current outages behind the «⚡ Немає світла? Аварійні» button) in `render.py`, plus `REGION_*`, `SITE_*` and `OUTAGES_*` (when that page is not the site itself) in `texts.py`. The region button and the rest of `/add` then work.
7. Per-region features to decide: `Subscription.has_switching` (Ternopil only, it gates `remind_exact`), planned works (Ternopil only, `PlannedWorks`), the current-outage line in «Що далі» and today's «Графік» (`CurrentOutages`: Ternopil from the API, Volyn from the Mac's snapshot, Dnipropetrovsk only «графік не діє» during the operator's emergency shutdowns), and `/status`.

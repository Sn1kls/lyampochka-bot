# Volynoblenergo: research notes

Status: **built** (2026-11-08, branch `feature/volyn-oblast`).
- Schedules: the PNG images from the inneti API, decoded from pixels on the server (see "Schedule images").
- Address → queue: exported weekly on the owner's Mac and imported into the bot (see "Weekly catalogue"). Only this part needs a Ukrainian IP.
- First researched 2026-10-18 and postponed. Reopened 2026-11-08: the owner lives in Ківерці (Volyn oblast) now and wants schedules for the whole oblast.

## Sources checked

| Source | Usable? | Why |
|---|---|---|
| Schedule form on energy.volyn.ua (`hrafik-vidkliuchen/`) | yes, the only live source | server-rendered PHP, HTML answers |
| Queue lookup on energy.volyn.ua (`cherga/`) | yes | HTML table, address → queue, works with no outages |
| `api-voe-poweron.inneti.net/api` (same platform as Ternopil's API) | no | cut down: archive images and accidents only |
| Telegram channel `@energy_volyn_official` | no | free-text posts about changes, not full schedules |
| Viber bot `viber://pa?chatURI=botvoe`, cabinets `ok.prosvitlo.com`, `kabinet.prosvitlo.com` | no | need a personal account number |
| Third-party Telegram bots (`@SvitloOkBot`, `@Volin_Oblenergo_grafikybot`, …) | no | unofficial, unknown sources |

## Schedule form (`hrafik-vidkliuchen/`)

- Page: `https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/hrafik-vidkliuchen/`.
  - The page says the data refreshes every 60 minutes and shows «Оновлено: DD-MM-YYYY HH:MM». The stamp moves hourly.
- Search: `POST …/hrafik-vidkliuchen/pagephp.php`, form-encoded:
  - `formGpvDate`: `YYYY-MM-DD`; the `<select>` offers only today and tomorrow;
  - `formCity`: required, free text, name only (no «м.», «с.»), case-insensitive;
  - `formStreet`: optional, free text, name only (no «вул.», «пр.»);
  - `searchForm=searchFromForm`.
- **Session.** The search needs a PHP session.
  - GET the form page first; it sets `PHPSESSID` (and Cloudflare's `__cf_bm`). Then POST with those cookies.
  - One session serves **one** search. A second POST on the same session, or a POST with no session, gets a page with «Повернутись до форми пошуку» and no result (fixture `voe_gpv_no_session.html`).
  - So every search costs two requests: GET form + POST.
- Answers seen so far (no outages in Volyn on 2026-11-08 and 2026-11-09):
  - «Фільтр: Нас. пункт <city> Очистити» + «Вибраної адреси у графіках не знайдено.» (fixture `voe_gpv_not_found.html`; checked for Луцьк and Ківерці).
  - The response is a full HTML page (~40 KB); without results it has no `<table>`.
- Not seen yet: a page with an actual schedule.

## Queue lookup (`cherga/`)

- Page: `https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/cherga/`.
- `POST …/cherga/` with `formCity` + `formStreet`, both required. No session needed.
- Answer: an HTML table (fixtures `voe_cherga_kivertsi_nezalezhnosti.html`, `voe_cherga_lutsk_lesi_ukrainky.html`):

  | Район | Нас. пункт | Вулиця | Будинок | Черга у ГПВ | Черга у ГАВ |
  |---|---|---|---|---|---|
  | Луцький | Ківерці | Незалежності | 1, 1А, 2, 3, 3А, 4, 6 | 6.1 | Не залучено |

- Queues are `1.1`-style subqueues, like Ternopil. ГПВ (hourly schedules) has queues 1–6; ГАВ (emergency schedules) has 1–10.
- «Не залучено» = the address is not in the schedules (critical infrastructure etc.), like Ternopil's «Не входить».
- «Будинок» is a comma-separated list per row, with mixed case and spaces (`22 а`, `14а`, `3А`) and a `<>` placeholder.
  - One building can appear in several rows (Незалежності 19, 26, 29).
  - All rows in the sample have the same queue, so a building with two queues was not seen.
- No match: the page has the filter line and «…не знайдено» and no table (fixture `voe_cherga_none.html`).
- The site says the queue of an address is fixed from 1 October to 1 October (the yearly schedule approval).
- Both fields match substrings, and results are not capped:
  - `Ківерці` / `а` → 441 rows, 93 streets;
  - `Ківерц` / `Незалежн` → 16 rows;
  - `а` / `Незалежності` → 579 rows in 90 settlements.
- So the whole oblast's address → queue table can be exported from a Ukrainian IP: discover settlements, then query each settlement by vowels at 1 req/s.
- The «Черга у ГАВ» column holds a number (e.g. `8`) or «Не залучено».
- Full export (`scripts/export_volyn_queues.py`, 2026-11-08):
  - 100 requests (10 × 10 vowels), 195 s;
  - single responses up to ~1.9 MB / 0.7 s (`а` / `а`: 11 111 rows);
  - result: 1046 settlements in 4 districts, 257 153 unique buildings, 824 KB gzip;
  - 1470 buildings have 2 queues, 41 have 3–4;
  - 573 buildings have «Не залучено» in one row and a queue in another, so they count as in the queue;
  - 13 995 buildings are «Не залучено» only;
  - 54 settlement names repeat across districts, so the district is shown next to them.

## inneti API (`api-voe-poweron.inneti.net/api`)

- The archive page (`hrafik-vidkliuchen-arc/`) embeds `https://voe-poweron.inneti.net/schedule_arhiv`. It is the same «Чому немає світла?» platform as Ternopil's `poweron.toe.com.ua`.
- The Volyn backend exposes much less than Ternopil's:
  - `archive_gpv_graphs?dateGraph[after]=…&dateGraph[before]=…` → a PNG image per day (`imageUrl.contentUrl`, e.g. `/media/2026/01/…_GPV.png`), no slot data. 23 items for 14–16 Jan 2026.
  - `options` → 200 (sync timestamps).
  - `pw_cities` → 200 but empty.
  - `a_gpv_g`, `pw-accounts/building-names`, `schedule_queues` → 404. `/api` redirects to a login page; `/api/docs.jsonld` → 404.
- The site bundle (`static/js/main.0e0fcca0.js`) calls only: `archive_gpv_graphs`, `pw_streets`, `pw_accidents`, `pw_accident_planeds`, the `*_histories` endpoints, `options`, `nek_command`, `healthcheck`.
- So `ToeClient` cannot be reused for Volyn.

## Schedule images: the usable live source (2026-11-08)

- The "archive" is effectively a live feed:
  - every revision of a day's schedule becomes a new `archive_gpv_graphs` item within minutes;
  - tomorrow's schedule appears the evening before;
  - on 14–16 Jan 2026 there were 23 items, 3–7 revisions per day.
- Query: `GET /api/archive_gpv_graphs?page=1&dateGraph[after]=YYYY-MM-DDT00:00:00+02:00Z&dateGraph[before]=YYYY-MM-DDT00:00:00+02:00Z`.
  - 30 items per page; 616 items in total from 02.12.2025 to 19.10.2026.
  - A malformed date makes the server ignore the filter and return everything.
  - Item fields: `dateGraph` (the day), `dateCreate` (publication time) and `imageUrl.contentUrl` (`/media/YYYY/MM/<id>_GPV.png`, served by the API host). `imageMobileUrl` is the same file.
  - The current schedule of a day = the item with the newest `dateCreate` for that `dateGraph`.
- **Both the API and the images answer the production server (200).** No Cloudflare challenge there.
- The image is machine-drawn and identical in every sample (Dec 2025, Jan, Feb, Mar, Oct 2026):
  - PNG, 1750 × 2250, 8-bit RGB, ~130 KB;
  - title «ГПВ на DD.MM.YYYY» and «Інформація станом на HH:MM DD.MM.YYYY»;
  - two grids, 00:00–12:00 and 12:00–24:00: 12 rows (subqueues 1.1 … 6.2) × 24 half-hour cells, separated by white lines;
  - only two cell colours: `(185, 200, 215)` «наявне електропостачання» = ON and `(68, 110, 155)` «відсутнє електропостачання» = OFF. The time header row has the OFF colour too;
  - no "switching" colour.
- Decoding needs no AI:
  - find the grid from the white lines;
  - drop the header row of each half;
  - read the colour at the centre of each of the 12 × 48 cells;
  - any other colour or a different grid size → `ApiSchemaError`.
- A prototype decoded 16.01.2026 correctly: checked by eye for 1.1, 1.2, 3.2 and 6.1, including blocks across noon. An all-ON day (12.02.2026, outages cancelled) decodes as empty.
- A vision LLM is not needed and would be worse here: it costs money, it is not deterministic, and it needs a prompt-injection review.
- The address → queue lookup (`cherga/`) is still only on energy.volyn.ua, which the server cannot reach.

## Server access

- From the production VM (Oracle Cloud, Stockholm) every energy.volyn.ua page answers **403** with a Cloudflare «Just a moment...» challenge (checked with an honest User-Agent).
- From the owner's Mac (residential Ukrainian IP) every page answers 200.
- The toe API still answers the server (200).
- **We do not try to get around the challenge** (no fake browser User-Agent, no challenge solvers, no proxies picked to evade it).
- Ways forward, for the owner to choose:
  1. Ask Volynoblenergo to open the inneti API for schedules (like Ternopil) or to allow the server's IP. Contacts: call center 0 800 21 01 31; the site's «Повідомити про розбіжності у графіку» form.
  2. Fetch Volyn data from a device in Ukraine (Mac, Raspberry Pi) and pass it to the bot. Needs an HTTP endpoint in the bot. Weakness: the device loses power during outages, exactly when schedules matter.
  3. Move the whole bot to hosting the site does not challenge. Unknown which hosting passes; not tested.

## Probe

- `scripts/probe_volyn.py`: stdlib only, sequential, at most 1 request/second, public street names only.
- Saves raw HTML to `tests/fixtures/voe_*.html`.
- When a schedule search answers anything other than «не знайдено», it saves that page as `voe_gpv_<day>_<city>.html` for the parser.

## What is still unknown

- The schedule result format: whether results are per address or per queue, and how hours, half-hours and "switching" are shown.
- Whether the server can be given access (see "Server access").

## How it is built

- `adapters/voe_api`: `VoeClient` (`ScheduleSource`).
  - It reads the archive list for today and tomorrow, takes the newest revision per day, and decodes the image (stdlib PNG reader + grid scan, ~1.3 s, in a thread).
  - The list is cached for 60 s, so one poll pass over 12 subqueues costs one list request; decoded images are cached by URL.
  - Slots use toe's raw codes ("1" OFF, "0" ON). The image has no "switching" colour.
- Subqueue keys are namespaced: `voe:6.1` (`core/domain/providers.py`). Ternopil keys stay plain, so no stored data moved.
  - A subscription's region is the prefix of its queues (`Subscription.provider`); every subscription has at least one queue.
  - `SchedulesByProvider` routes polling; `SubqueueChecker` takes one catalogue per region; planned works are Ternopil-only.
- `voe_buildings` table (migration `5c2d8e4f1a90`) + `adapters/db/voe_catalog.py`: `VoeCatalog` is the Volyn `CatalogSource`.
  - Ids are crc32 of the names (31 bits), so they stay the same across imports and the daily queue re-check finds the building again.
  - «Не залучено» rows are stored with no queue; a building with a queue in another row counts as in that queue.
- `/add` starts with a region button; the rest of the wizard is shared.

## Weekly catalogue

- `scripts/export_volyn_queues.py`: 10 × 10 vowel grid over the lookup, 1.5 s between requests, ~3 min.
  - Building names are unified: «22 а», «22-а» and «22A» (Latin) all become «22А».
  - Output: gzip JSON Lines, ~0.8 MB.
- `scripts/sync_volyn_queues.sh`: export, then `ssh … docker compose run --rm --no-deps -T bot python -m poweron.import_voe < file`.
  - `make sync-volyn TARGET=…` runs it once.
  - `make install-volyn-sync TARGET=…` installs a launchd job: Mondays 10:00, run on wake if missed, log in `~/Library/Logs/lyampochka-volyn-sync.log`.
- Import:
  - one transaction (~2 s on the Mac for 257 k rows); SQLite's busy timeout is raised to 30 s so the bot waits instead of failing;
  - refused below 80 % of the stored buildings unless `--force`;
  - a row with an empty or over-long name is skipped and counted, so one odd address does not block every import; a file not in the export format is refused;
  - the cached Volyn lists (`voe:*` in `catalog_cache`) are dropped in the same transaction, so the wizard sees the new catalogue at once;
  - runs as `python -m poweron.import_voe` in a short-lived container (`docker compose run --rm`), without aiogram: peak ~310 MB, was ~700 MB;
  - reports «N buildings (was M), K changed, S rows skipped» to stdout and, if anything changed, to the admin chat.
- `VoeCatalogAge`: a daily admin alert when there was no import yet or the last one is older than 10 days.
- The database grows by ~29 MB with the catalogue. The nightly backup goes to Telegram, whose bot upload limit is 50 MB, so watch the size.

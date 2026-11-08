# Volynoblenergo: research notes

Status: **source found, not built** (2026-11-08).
- The schedule images from the inneti API are reachable from the server and decode reliably (see "Schedule images").
- Only the address → queue lookup on energy.volyn.ua is blocked from the server by a Cloudflare challenge (see "Server access").
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

## Agreed plan (2026-11-08, on hold until access is solved)

The owner chose:
- build in parts;
- a "catcher" in the server worker;
- an `/add` flow of region → text → buttons.

1. Region in data:
   - migration `subscriptions.provider` (`toe` / `voe`); existing rows become `toe`;
   - Volyn subqueue keys are namespaced (`voe:6.1`), so `schedule_versions`, `subqueue_polls` and `subscription_subqueues` need no change; display strips the prefix;
   - Volyn subscriptions store city and street names (there are no numeric ids).
2. Adapter `adapters/voe_site`:
   - httpx + stdlib `html.parser`, no new dependency;
   - 1 req/s, a fresh session per schedule search;
   - `ApiSchemaError` on any layout change;
   - parses the queue table, including duplicate rows, `<>` and «Не залучено».
3. core:
   - a port for the address → queue lookup;
   - polling, the queue re-check and planned works skip Volyn subscriptions: there is no schedule source yet, the queue is fixed for a year, and there is no planned-works API.
4. Catcher in the worker:
   - hourly, today and tomorrow, for the cities of Volyn subscriptions (Луцьк if there are none);
   - «не знайдено» is ignored;
   - any other page goes to the admin chat as a file, once per content.
5. Telegram:
   - `/add` starts with a region choice;
   - Volyn: city as text → street as text → building buttons (with the street name when several streets match) → queue → confirm;
   - «Не залучено» is explained;
   - «Графік» for a Volyn address says there are no Volyn schedules yet.
6. Stage 2, after the first captured schedule: parse it into `DaySchedule`. Pushes, reminders and `/next` then work unchanged.

Risks:
- The free-text search can match several settlements or streets.
- Ternopil users get one extra tap in `/add`.

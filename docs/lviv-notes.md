# Lvivoblenergo: research notes

Status: **built** (2026-11-23, branch `feature/lviv-oblast`); researched on `chore/lviv-research`.

Short version: Lviv is closer to Ternopil than to Volyn. The schedule is published as text per group, the address → queue lookup is a public JSON API on the same «Чому немає світла?» platform, and both answer the production server. No image decoding, no import from the Mac.

## Sources

| Source | Usable? | Why |
|---|---|---|
| `api.loe.lviv.ua/api/menu_items/{238,256}` (CMS behind `poweron.loe.lviv.ua`) | yes, schedules | today / tomorrow as HTML text per group, 3 KB, not cached by Cloudflare (`cf-cache-status: DYNAMIC`) |
| `api.loe.lviv.ua/api/menus?type=photo-grafic` | only for research | the same two items plus `Arhiv` with every revision since 07.2024; 1.3 MB |
| `power-api.loe.lviv.ua/api` (inneti platform, like Ternopil's API) | yes, catalogue | `pw_otgs`, `pw_cities`, `pw_streets`, `pw_accounts` |
| `api.loe.lviv.ua/media/<id>_GPV.png` | not needed | the same schedule as a picture |

## Server access

From the production VM (Oracle, Stockholm), with an honest User-Agent, on 2026-11-23: `poweron.loe.lviv.ua`, `api.loe.lviv.ua` (JSON and media) and `power-api.loe.lviv.ua` all answer **200**. No Cloudflare challenge.

## Schedule text

- `GET https://api.loe.lviv.ua/api/menu_items/238` is «Today», `…/256` is «Tomorrow» (ids from the `photo-grafic` menu the site reads). Fixtures: `loe_menu_item_today.json`, `loe_menu_item_tomorrow.json`.
- The schedule is in `rawHtml` (`rawMobileHtml` holds the same). `imageUrl` is the PNG of the same schedule.
- «Tomorrow» is an empty item (`rawHtml: ""`) until it is published.
- Format, the same in all 550 text revisions of the archive (30.10.2025 – 23.11.2026), only 5 line shapes:

  ```
  <p><b>Графік погодинних відключень на 23.11.2026</b></p>
  <p><b>Інформація станом на 08:08 23.11.2026</b></p>
  <p>Група 1.1. Електроенергії немає з 16:30 до 20:00.</p>
  <p>Група 1.2. Електроенергії немає з 16:30 до 20:00, з 22:00 до 24:00.</p>
  <p>Група 2.1. Електроенергія є.</p>
  ```

  - always the 12 groups `1.1` … `6.2`, each once;
  - up to 5 intervals per group, separated by «, з»;
  - times are always `HH:MM`, on `:00` or `:30`; the day ends with `24:00`;
  - only two states: OFF and ON. No "switching" state, like Volyn.
- The day comes from «на DD.MM.YYYY», the revision time from «станом на HH:MM DD.MM.YYYY» (Kyiv wall time). 107 of 550 revisions were published for the next day, mostly between 16:00 and 21:00.
- Up to 14 revisions per day; each one replaces the item's text in place.
- **Garbage seen once:** a revision sent 30.10.2025 07:07 says «на 12.08.2024» and has every interval `з 00:00 до 00:00`. So a day that is neither today nor tomorrow is ignored, and an empty or reversed interval is an `ApiSchemaError`.

## Groups

`GET api.loe.lviv.ua/api/menus?page=1&type=power-group&jsonld=1` lists «Група 1.1» … «Група 6.2». Same names as in the schedule text; nothing else in it the bot needs.

## Catalogue (`power-api.loe.lviv.ua/api`)

- `pw_otgs?pagination=false`: 85 hromadas (`id`, `name`, `code`).
- `pw_cities?pagination=false&otg.id=`: 2034 settlements, 400 KB, `{id, name, codeOtg, otg: {name}}`.
  - 139 names repeat, so the hromada is shown next to the name, like the site («Львів (Львівська ОТГ)»).
- `pw_streets?pagination=false&city.id=693`: Lviv has 1658 streets, `{id, name, city}`. Answers a **bare JSON list**, not a hydra collection.
  - Names are messy: «Ринок. пл.», «Ринок площа», «пл.Ринок. 21-вул. Галицька. 1» all exist.
- `pw_accounts?pagination=false&city.id=…&street.id=…`: **one row per consumer account**, not per building. Fixture `loe_pw_accounts_rynok.json` (5 buildings of пл. Ринок, Lviv).
  - Row: `id` (internal record id), `buildingName`, `chergGpv` (`"3.1"` or «Не входить»), `chergGav`, `chergAchr`, `chergGvsp`, `chergSgav`, `city`, two booleans. No account numbers, no names.
  - пл. Ринок: 533 rows, 47 buildings, up to 43 rows per building.
  - 19 of 47 buildings mix rows: mostly «Не входить» + one queue (14: 6 × «Не входить», 4 × `1.1`), some two queues (9: 15 × `4.1`, 2 × `3.1`).
  - Building names: `""`, `12/40`, `13-14`, `43, ПРИМ.15`.
- The site's own logic: when a building has one queue it shows it; when several, it asks for the 10-digit personal account (`pw_accounts?acc=…&city.id=…&street.id=…&building.name=…`). The bot instead lets the user pick, as it already does for Ternopil buildings in several queues.
- Cloudflare caches the catalogue endpoints (`cf-cache-status: HIT`), which is fine for a catalogue.

## Probe

`scripts/probe_lviv.py`: stdlib only, sequential, at most 1 request/second, one public address (пл. Ринок, Lviv). Prints the shapes and saves the fixtures above.

## Still unknown

- When «Tomorrow» gets filled (the archive says mostly 16:00–21:00), and what happens to both items at midnight: does «Today» switch to the former «Tomorrow» at once? Run the probe once in the evening and once after midnight.
- Whether «Today» ever carries yesterday's text for a while after midnight. The day in the text decides, so the parser is safe either way.
- Planned works: `pw_accidents` exists (the site's accident archive); not looked at.

## How it is built

- `adapters/loe_api/schedule.py`: `parse_schedule` turns the text into 12 groups × 48 slot codes (toe's `"1"` OFF, `"0"` ON). Spacing (`&nbsp;`) and inline tags are normalised away first. Strict on group lines: a missing, repeated or unreadable group, or an empty, reversed or off-grid interval, is an `ApiSchemaError`. Other lines (a note) are logged and skipped.
- `adapters/loe_api/client.py`: `LoeClient` is both the Lviv `ScheduleSource` and `CatalogSource`.
  - Schedules: «Today» + «Tomorrow» per poll pass, cached 60 s, so 12 subqueues cost 2 requests. A day that is neither today nor tomorrow is dropped; when both items carry the same day, the later «станом на» wins. An unreadable item is logged as an error and skipped; the poll fails only when no usable schedule is left.
  - Catalogue: `pw_cities` (hromada as `otg_name`), `pw_streets`, and `pw_accounts` gathered by building name: «Не входить» next to a queue counts as that queue; a value that is not one of the 12 groups is no queue (logged unless it is «Не входить»); a nameless row is dropped. Building ids are crc32 of the name. Each street is cached 60 s, so `/add` and the daily queue re-check ask a street once.
- Pacing and retries live in `adapters/paced_http.py`, shared with `voe_api`.
- Subqueue keys: `loe:3.1`. No migration, no new settings.
- Like Volyn: no switching state, so no `remind_exact`; no planned works.
- The garbage revision seen once (all `00:00 до 00:00`) is an `ApiSchemaError`, not a skipped day: if it is the only text, the poll fails, users keep the last known schedule and the admin is alerted. That is on purpose: the oblenergo published nonsense as today's schedule.

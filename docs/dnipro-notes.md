# Dnipropetrovsk oblast: research notes

Status: **built** (2026-11-27, branch `feature/dnipro-oblast`); researched on `chore/dnipro-research`.

Short version: the oblast has two distribution operators, **DTEK Dnipro Grids (ДнЕМ)** and **CEK (ЦЕК)**, and both are served by one public JSON API of YASNO (DTEK's supplier), `app.yasno.ua`. It gives schedules per group as minute intervals and the address → group lookup for both operators. Closer to Lviv than to Volyn: no images, no export from the Mac: the production server gets through Incapsula.

## Sources

| Source | Usable? | Why |
|---|---|---|
| `app.yasno.ua/api/blackout-service/public/shutdowns/...` | yes, schedules and catalogue | JSON, both operators, `cache-control: max-age=300, public` |
| `www.dtek-dnem.com.ua/ua/shutdowns` | no | an Incapsula JS challenge even for a plain GET from the Mac; we never get around such a challenge |
| `cek.dp.ua` (CEK's own site, Joomla) | no, only a link | open, but its schedule form answered «На цей день відключень немає» for 27.11 while CEK did cut queues that day (YASNO and the news agree); stale |

The Home Assistant integration `denysdovhan/ha-yasno-outages` reads the same API (endpoint list in its `api/const.py`); it was the starting point. It does not handle the city level.

## Server access

`app.yasno.ua` sits behind Incapsula: `app.yasno.ua/robots.txt` answers the challenge page, the API paths answer JSON.

From the production VM (Oracle, Stockholm), with an honest User-Agent, on 2026-11-27: `addresses/v2/regions` answered **200 `application/json`** with both regions. No Mac export like Volyn. The other endpoints were checked from the Mac only. The client must still treat an HTML answer as a source error: Incapsula may start challenging at any time, and then we stop (no headless browsers, no workarounds).

```bash
ssh ubuntu@<server> 'curl -s -A "poweron-bot/0.16 (personal use)" -w "\n%{http_code} %{content_type}\n" https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2/regions | tail -c 400'
```

## Regions and operators

`GET .../addresses/v2/regions` (fixture `yasno_regions.json`):

```json
[{"id": 25, "value": "Київ", "hasCities": false, "dsos": [{"id": 902, ...}]},
 {"id": 3, "value": "Дніпро", "hasCities": true, "dsos": [{"id": 301, "name": "ДнЕМ"}, {"id": 303, "name": "ЦЕК"}]}]
```

Region `3` is the whole oblast. Every other call takes `regionId=3` and `dsoId=301|303`.

## Schedules

`GET .../regions/3/dsos/{dso}/planned-outages` (fixtures `yasno_planned_outages_301.json`, `_303.json`; 8.5 KB and 5.6 KB):

```json
{"17.1": {
  "today":    {"date": "2026-11-27T00:00:00+02:00", "status": "ScheduleApplies",
               "slots": [{"start": 0, "end": 240, "type": "NotPlanned"},
                         {"start": 240, "end": 480, "type": "Definite"}, ...]},
  "tomorrow": {"date": "2026-11-28T00:00:00+02:00", "status": "WaitingForSchedule", "slots": []},
  "updatedOn": "2026-11-27T09:30:02+00:00"}}
```

- **Groups differ per operator:** ДнЕМ has 18 groups `1.1` … `18.1` (subgroup always 1), CEK has 12 groups `1.1` … `6.2`. The same name means different schedules in the two operators, so a subqueue key must carry the operator, not just the oblast.
- `start`/`end` are minutes from the Kyiv midnight of `date`; the day ends at `1440`. On 27.11 every slot was on the 30-minute grid (checked by the probe).
- Slot types: `Definite` = OFF, `NotPlanned` = ON. The integration also knows no "switching" state, so like Volyn and Lviv: no 🟡, no `remind_exact`.
- Day statuses seen: `ScheduleApplies`, `WaitingForSchedule` (tomorrow not published yet, empty slots), `NoOutages` (one `NotPlanned` slot 0–1440). The integration also knows `EmergencyShutdowns`: the news on 27.11 said «графіки ДТЕК не діють, екстрені відключення» at some point of the day. Not seen in the API yet; its slots are unknown.
- `updatedOn` is per group (UTC). ДнЕМ and CEK update separately.

## Catalogue

All under `.../addresses/v2/`, each takes `regionId=3&dsoId=…`:

| Call | Answer | Notes |
|---|---|---|
| `cities?query=` | `[{id, value}]` | empty query lists them all: ДнЕМ 1075, CEK 11 (fixture `yasno_cities_303.json`) |
| `streets?cityId=&query=` | `[{id, value}]` | **search only**: case-insensitive substring, at least 3 letters, at most 20 results; empty query → `[]` |
| `houses?cityId=&streetId=&query=` | `[{id, value}]` | empty query works but also stops at 20; `query` filters by substring |
| `group?cityId=&streetId=&houseId=` | `{"group": 17, "subgroup": 1}` | → `17.1`; without `cityId` it is a 404 `EntryNotFound` |

- Names are messy: «м. Кам’янське» and «м. Кам'янське» are two cities; «вул. Шевченка Тараса», «просп. Тараса Шевченка», «просп. Шевченка Тараса» are three streets in Kamianske, each with its own houses. Corner entries exist («ріг вул. Пастера/пр. Дмитра Яворницького»).
- Houses carry inputs: «1 ввод 1», «1 ввод 2», «46/нежпр1,Х ввод 1», «б/н». Each entry is its own `houseId`, and inputs could be in different groups (not seen yet).
- **The operators overlap.** CEK serves parts of Dnipro, Kryvyi Rih, Pavlohrad, Zhovti Vody, Vilnohirsk and six villages; the rest is ДнЕМ. In Dnipro «вул. Братів Горобців» exists in both: house 36 is CEK only. The user cannot be asked which operator they have, so the bot has to search both and merge.
- City ids look shared (Dnipro is `6` in both), street ids are not (Горобців: `2608` in ДнЕМ, `147` in CEK).

## Probe

`scripts/probe_dnipro.py`: stdlib only, sequential, at most 1 request/second, public addresses (просп. Яворницького Дмитра and вул. Братів Горобців, Dnipro). Prints the shapes and saves the `yasno_*` fixtures; `--dry` saves nothing. It stops on an HTML answer (the Incapsula challenge answers 200).

## Decisions (owner, 2026-11-27)

1. **One button, the address decides the operator.** «Дніпропетровська» searches both operators; there is no «ДТЕК чи ЦЕК?» step, since most people do not know theirs. Two providers inside (`dnem:17.1`, `cek:1.2`), since group names collide.
   - A house found in one operator takes its queue. A house found in both offers both queues on the usual «Яку відстежувати?» screen with «Усі»; the extra one can be switched off in the address settings (✅/🚫).
2. **The operator next to the queue**, Dnipropetrovsk only: «Черга 17.1 (ДТЕК)», «Черга 1.2 (ЦЕК)», on the picking screen, in the settings, «Графік» and pushes. Matches how the news write it, and tells two «1.1» apart.
3. **Same-named cities and streets merge** into one button (by normalised name: «м. Дніпро» = «Дніпро»); the house is looked up in every operator that has the street. City ids are *not* shared (`8` is Zhovti Vody in CEK, Kamianske in ДнЕМ), so merging is by name only. Differently named streets stay apart.
4. **House number as text** for this region: «Напиши номер будинку», then the matches as buttons (YASNO stops at 20).
5. **Inputs merge**: «1 ввод 1» and «1 ввод 2» are one building «1»; different groups go through the queue picking above.
6. **`EmergencyShutdowns`**: a line «⚠️ Зараз екстрені відключення, графік не діє» in «Графік» and «Що далі»; no push and a log for the admin until the status is seen live.
7. **Links** per operator: DTEK `dtek-dnem.com.ua/ua/shutdowns` (a person in a browser gets through), CEK its «ГАВ» page on `cek.dp.ua`.
8. **Schedules only** at first: no current-outage line by building, no planned works.
9. **Region buttons in alphabetical order** everywhere, `/status` too: Волинська, Дніпропетровська, Львівська, Тернопільська.
10. **No broadcast**: the button just appears; the owner tells the people who asked.

## Still unknown

- When «tomorrow» gets filled, and how often `updatedOn` moves in a day.
- `EmergencyShutdowns`: its slots and how long it lasts.
- Whether CEK ever publishes on YASNO late compared with its own channels.

## How it is built

- `adapters/yasno_api/client.py`: `YasnoClient` is the schedule source of both providers, the `SearchCatalogSource` of the region and the `SuspensionSource` of both providers.
  - Schedules: one `planned-outages` request per operator, cached 60 s, so a poll costs 2 requests. Minutes become 48 half-hour codes (`Definite` → OFF, `NotPlanned` → ON). `WaitingForSchedule` and `EmergencyShutdowns` days give no schedule (the last version stays); an unknown status or type, or a slot off the 30-minute grid, is an `ApiSchemaError`; an Incapsula page is one too (`PacedHttp` wants JSON).
  - Catalogue: cities and streets of both operators merge by `normalise`d name; the item id carries both operators' ids (`DnEM id × 100 000 + CEK id`, 0 for absent), so the daily queue re-check finds the house in both without the user's text. One operator's own duplicates stay apart. Houses merge their inputs («1 ввод 1/2» → «1»); building ids are crc32 of the name. Streets need 3 letters.
  - Queues: once a house is picked, `houses?query=<name>` per operator and `group` per matching entry (2–4 requests).
- `Catalog` takes either kind of source: a `SearchCatalogSource` is searched live (no 24 h cache for streets and houses), `asks_building_number` tells `/add` to ask for the number, and an empty queue list refuses the address.
- `/add`: «Дніпропетровська» (region `dnipro`) → city → street → «Напиши номер будинку» → exact match or buttons → queue picking when inputs or operators differ.
- `queue_name` adds the operator («17.1 (ДТЕК)», «1.2 (ЦЕК)») everywhere a queue is shown.
- `CurrentOutages` asks `suspended` first: «⚠️ Зараз екстрені відключення, графік не діє» in «Що далі» and today's «Графік». No push.
- No migration: keys `dnem:17.1`, `cek:1.2` fit the existing columns. No switching state, no planned works, no `remind_exact`.
- Checked live through the real client on 27.11: Dnipro, вул. Братів Горобців (Дмитра Кедріна) 36 → `cek:1.2`; просп. Яворницького Дмитра 1 → `dnem:17.1` and `dnem:18.1` (its two inputs are in **different** groups, so merging inputs with queue picking matters).
- Known limits:
  - A street spelled differently by the two operators is two buttons («вул. Братів Горобців» in DnEM, «… (Дмитра Кедріна)» in CEK); the house is only under one of them.
  - YASNO stops at 20 houses and streets per search: a short number like «1» may not show every match; typing more of it narrows it.
  - Same-named villages of the two operators merge into one city; a house number in both then offers both queues.
  - The `EmergencyShutdowns` line is untested live: the status has not been seen yet.

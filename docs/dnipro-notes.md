# Dnipropetrovsk oblast: research notes

Status: **researched** (2026-11-27, branch `chore/dnipro-research`); not built yet.

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

## Design points for the build (to grill before a plan)

1. **One button, two operators.** «Дніпропетровська» maps to two providers (`dnem:17.1`, `cek:1.2`), since group names collide. `REGIONS` is keyed by provider today.
2. **Search-only catalogue.** `CatalogSource.streets(city_id)` returns a full list and `Catalog` filters it; YASNO can only search, 20 at a time. Needs the query passed to the source (a port change), at least for streets.
3. **Houses.** The bot shows buildings as buttons; YASNO stops at 20. Either ask for the house number as text (then `houses?query=`), or show the first 20 and search past that.
4. **Inputs («ввод 1/2»).** Merge them into one building with all their groups, like Ternopil buildings in several queues, or show them as they are.
5. **`EmergencyShutdowns`.** What to show and push when the day is that status: no schedule, or the last one.
6. Links for «⚡ Немає світла? Аварійні» and the site note: the DTEK page and the CEK «ГАВ» page, per operator.
7. Region button order: alphabetical (owner's request): Волинська, Дніпропетровська, Львівська, Тернопільська.

## Still unknown

- When «tomorrow» gets filled, and how often `updatedOn` moves in a day.
- `EmergencyShutdowns`: its slots and how long it lasts.
- Whether a house's inputs are ever in different groups.
- Whether CEK ever publishes on YASNO late compared with its own channels.

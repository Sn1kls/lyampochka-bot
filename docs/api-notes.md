# toe API notes (Phase 0)

Probed 2026-10-17 ~17:45 Europe/Kyiv with `scripts/probe.py` (≈30 sequential requests, 1 req/s)
and by reading the site client bundle `https://poweron.toe.com.ua/static/js/main.c63cd454.js`.
**This file overrides SPEC §2 wherever they differ.** Raw responses: `tests/fixtures/`.

## Summary of what changes against SPEC §2

1. **`X-debug-key` is mandatory and it alone selects the subqueue.** `group` and `time` are ignored by the server.
2. **To poll a subqueue you need an address in it.** `/a_gpv_g` cannot be asked "give me 4.1": the bot must
   keep one representative address (`cityId/streetId/buildingName`) per `cherg_gpv`, e.g. from any subscription.
   Caching by subqueue (SPEC §3.1) still holds: every address of one subqueue gets identical data.
3. **Cloudflare caches `/a_gpv_g` by URL for up to 2 h** (`s-maxage=7200`). See "Caching" — open question for the owner.
4. Empty results come in two shapes: `"hydra:member": null` and `"hydra:member": []`.

## Slot semantics (SPEC §2.3.1) — confirmed from the site client and visually

The owner compared the site's rendering of subqueue 4.1 for 2026-10-17 with the fixture: every grey (`10`),
dark (`1`) and white (`0`) half-hour matches slot by slot. The site labels the last cell `23:00–23:59`.

The site paints each half-hour slot with this function and legend (decoded from the bundle):

| value | site colour | site legend text | our `SlotState` |
|---|---|---|---|
| `"1"` | dark `#1F1755` + light-off icon | «вимкнення електроенергії» | `OFF` |
| `"10"` | grey `#B3B3B3` | «час на перемикання (можлива відсутність електроенергії)» | `SWITCHING` (possible outage) |
| `"0"` | white + light-on icon | «подача електроенергії» | `ON` |
| anything else / missing slot | white (site treats as `"0"`) | — | `UNKNOWN` + WARNING (SPEC §5.1, stricter than the site) |

- `times` has exactly 48 keys `"00:00"…"23:30"`; each key is the **start** of a 30-minute slot. Last slot ends at 24:00.
- Only `0`, `1`, `10` seen (two subqueues, one day). In the sample `10` sits at both edges of every `1` block:
  `10:30=10, 11:00…13:30=1, 14:00=10` and `19:30=10, 20:00…21:30=1, 22:00=10` (matches SPEC §2.2 sample).

Fixture intervals for 4.1, 2026-10-17, checked by hand against the raw 48 slots in the fixture
(pin this list in the Phase 1 `parse_slots` test; don't generate it from the probe):
`00:00–10:30 ON, 10:30–11:00 SWITCHING, 11:00–14:00 OFF, 14:00–14:30 SWITCHING, 14:30–19:30 ON,
19:30–20:00 SWITCHING, 20:00–22:00 OFF, 22:00–22:30 SWITCHING, 22:30–24:00 ON`.

## Time zones (SPEC §2.3.2)

- **Slot keys are Europe/Kyiv wall-clock time** — confirmed: the site prints the keys as hour labels without any conversion.
- **`dateGraph`** (`"2026-10-17T00:00:00Z"`) is a calendar date, not an instant: the site renders it with
  `dayjs.utc(...).format("DD.MM.YYYY")`. Take the date part, ignore the `Z`.
- **`dateCreate`** (`"2026-10-17T14:16:05Z"`): the site also renders it with `.utc()` («Інформація станом на: 17.10.2026 14:16:05»),
  so it is either real UTC (17:16 Kyiv) or Kyiv time mislabelled `Z`. Unconfirmed.
  **Decision (owner, 2026-10-17): show it as is, without time-zone conversion, exactly like the site.**
  Low impact: update detection uses `data_hash` (SPEC §5.2), `dateCreate` is only shown as "станом на".
- Request params `after`/`before` are built by the site from the **local** date with a fake `+00:00` suffix:
  `after = (today − 1 day) "YYYY-MM-DDT12:00:00+00:00"`, `before = (today + 1 day) "YYYY-MM-DDT00:00:00+00:00"`.
  Reproduce exactly this (today in Europe/Kyiv).

## `/a_gpv_g` request (SPEC §2.3.3)

Each line is a separate cache-miss request (unique URL) for Ternopil, vul. Sadova 1 (subqueue 4.1):

| request | result |
|---|---|
| site-style: `group=4.1`, `time`, `X-debug-key` | 1 member, `dataJson` has only `4.1` |
| `group[]=4.1` (what axios sends: the site passes an array) | same |
| no `X-debug-key` | `"hydra:member": []` |
| `X-debug-key` only, no `time` | same as site-style |
| `group=1.1` or no `group` | still `4.1` — `group` ignored |
| address of subqueue 1.2 (Mykulynetska): own `time` + own key | `1.2` |
| our `time` + 1.2's key | `1.2` — key decides |
| 1.2's `time` + our key | `4.1` — `time` ignored |
| another building, same subqueue | identical body |

- `X-debug-key = base64(utf8("{cityId}/{streetId}/{buildingName}"))`; `time` = the same string without `/`.
  Still send `time` and `group` exactly like the site (cheap, and `time` keeps the CDN cache key per address).
- `dataJson` contains **only** the subqueue of the address. The site looks it up by the full trimmed `chergGpv`
  (`dataJson[String(cherg).trim()]`) and drops a `#suffix` only for display (`cherg.split("#")[0]`). So keep the
  whole trimmed value as the subqueue id; strip `#…` only when rendering. No suffix seen yet.
- Response is always the Hydra envelope here (even with `Accept: application/json`).
- Not seen but plausible (PHP/API Platform backend): `"dataJson": []` for an empty map, or a subqueue entry
  without `times`. The Phase 1 pydantic models should reject or normalise these, not crash.

## Rate limits, Cloudflare, User-Agent (SPEC §2.3.4)

- Behind Cloudflare (`server: cloudflare`, `cf-ray`). No 429, no challenge, no rate-limit headers in ~170 requests at 1 req/s (7 runs).
- A plain `Python-urllib` User-Agent works the same as ours (checked on a cache-miss URL, i.e. at the origin). We still send `poweron-bot/<ver> (personal use; contact: …)`.
- No auth, no cookies.

### Caching

- `/a_gpv_g`, `/pw_cities`, `/pw_streets`, `/pw-accounts/building-names` answer with
  `Cache-Control: public, max-age=900|3600, s-maxage=7200` and `cf-cache-status: HIT|MISS|EXPIRED`, `Age` up to minutes.
  `/pw_accident_planeds` is `DYNAMIC` (not cached).
- **The edge cache key is the URL only; `X-debug-key` is not part of it.** The cached site URL of Sadova 1 sent with
  the 1.2 address's key returned the cached 4.1 body. Caches differ per edge node: an early probe run sent the exact
  site URL *without* the key (~17:43); some nodes cached that `[]` and served it later to correct requests (`HIT`,
  `Age` counting from 17:43), while other nodes served 4.1. Side effect: site visitors checking Sadova 1 on
  2026-10-17 could get "no schedule" from those nodes until ~19:43. The probe now sends any non-site-like request
  to a unique URL.
  → The client must never send a `time` that doesn't match its `X-debug-key`, or it can poison the cache for that address.
  A request `Cache-Control: no-cache` does **not** bypass it. Any change in the query string (e.g. `before` moved by
  a few seconds) does — the origin answers fresh.
- Since the site URL for one address is constant for a whole day, a schedule update may reach the edge (and us)
  **up to ~2 h late** unless the backend purges the cache (unknown).
- **Decision (owner, 2026-10-17): bypass the edge cache.** `before` = tomorrow + the current Kyiv time of day
  (`2026-10-18T17:45:00+00:00`): unique per second for a whole day, and `after` changes with the date, so a URL
  never repeats within the 2 h TTL. Still before the day after tomorrow, so the result window is unchanged.
  ≈1 origin request per subqueue per poll. Only inside `adapters/toe_api`, always with matching `time` + `X-debug-key`.

## Missing data (SPEC §2.3.5)

- 17:45 Kyiv on 2026-10-17: **one** member (today only) — tomorrow not published yet. The site then shows only today.
- Two members: order not guaranteed; the site picks "tomorrow" as the one with the later `dateGraph`. Do the same.
- Window with no graphs (+30 days): `"hydra:member": null`, `"hydra:totalItems": 0` → treat `null` as `[]`.
- Widening `after` to 7 days ago still returns only today: the endpoint serves only "actual" graphs, no history.
- A day without outages: not observed yet (expected all `"0"`); handle both all-`"0"` and absent member.

## `chergGpv` values (SPEC §2.3.6)

- Seen: `"4.1"`, `"1.2"`, `"Не входить"` (vul. Sadova 23). Other `cherg*` fields also use `""`.
- `/a_gpv_g` for a «Не входить» building **still returns a schedule** (4.1 for Sadova 23), so the API cannot be trusted
  here. Like the site, decide from `building-names`: `chergGpv` in (`"Не входить"`, `""`, missing) →
  «за вашою адресою графіки не застосовуються». The site shows exactly this text for that case.

## Buildings in several subqueues

Verified live 2026-10-17. Some buildings have two sources of power supply and belong to several subqueues
(the site says «будинок має два джерела електропостачання»). For a building in Ternopil:

- `GET /pw-accounts/building-names?cityId=&streetId=` lists the row with only **one** `chergGpv` (`"4.1"`).
- `GET /pw-accounts/building-groups?cityId=&streetId=&buildingNames=<name>` returns
  `{"buildingGroups": [{"chergGpv": "2.2"}, {"chergGpv": "4.1"}]}` — all of its subqueues. The site builds its
  list of queues from this endpoint.
- `/a_gpv_g` for that address returns `dataJson` with **both** keys, `"2.2"` and `"4.1"`.

So the bot asks `building-groups` when a building is added, polls every subqueue of every subscription, and lets
the user choose which of them to get pushes for (the others can still be viewed).

## Catalog endpoints

- `/pw_cities?pagination=false` → plain JSON array, 1301 items `{id, name, codeOtg, otg:{name}}`. Ternopil `id=1032`.
- `/pw_streets?pagination=false&city.id=1032` → plain array, 299 items `{id, city:"/api/pw_cities/1032", name}`.
  The site strips the `вул.` prefix for display/search.
- `/pw-accounts/building-names?cityId=&streetId=` → `{filters:{cityId, streetId, otgId}, buildingNames:[…]}` as in SPEC.
- `/pw_accident_planeds?…` → plain `[]` for Sadova today; the shape of an item is in "Planned works" below.
- Also in the bundle, not needed now: `/pw-accounts/building-groups`, `/pw_accounts_by_acc?account=`.

## Planned works

Verified live 2026-10-17 (Phase 5).

- `GET /pw_accident_planeds?page=N&city.id=&street.id=&datePlanIn[after]=…` with `Accept: application/json` returns a
  plain JSON array (no Hydra envelope), about 29 items per page. An empty array means no more pages. The site also sends
  `otg.id` and `datePlanIn[before]`. Not cached by Cloudflare (`DYNAMIC`).
- Item: `id`, `city{id, name}`, `street{id, name}`, `dateEvent` (start), `datePlanIn` (planned end), `koment` (reason,
  may contain `\r\n`), `otg{…}`, `buildingNames` (comma-separated list, e.g. `"1, 3-А, 6, 6-А"`), `typeOff`.
- **The dates are Kyiv wall-clock time with a fake `+00:00` label** (the site formats them with `timeZone: "UTC"`):
  `08:30+00:00` means 08:30 Europe/Kyiv. The adapter keeps the clock fields, attaches Europe/Kyiv and converts to a real
  UTC instant. The `datePlanIn[after]` filter value is likewise Kyiv wall time without offset, e.g. `2026-10-17T21:40:00`.
- The filter is on `datePlanIn`, the planned end, so a work that has already started but not ended is still returned.
- `typeOff` is not confirmed for this endpoint; the domain and the texts ignore it.
- Sample (three items, no personal addresses): `pw_accident_planeds_1032_sample.json`.

## Fixtures

| file | what |
|---|---|
| `pw_cities.json`, `pw_streets_1032.json`, `building_names_1032_9985.json` | catalog |
| `a_gpv_g_4.1_2026-10-17.json` | main schedule sample (1 member, today only) |
| `a_gpv_g_1.2_2026-10-17.json` | another subqueue, same day |
| `a_gpv_g_empty.json` | `hydra:member: null` |
| `a_gpv_g_no_key.json` | `hydra:member: []` (no `X-debug-key`) |
| `a_gpv_g_not_included.json` | «Не входить» building still gets 4.1 |
| `pw_accident_planeds_1032_9985.json` | empty planned works |
| `pw_accident_planeds_1032_sample.json` | three real planned works for Ternopil |

No personal data: public catalog data and the SPEC sample address only.

# Khmelnytskyi oblast: research notes

Status: **built** (2026-11-27, branch `feature/khmelnytskyi-oblast`); researched on `chore/khmelnytskyi-research`.

Why this region: a friend in Kamianets-Podilskyi asked for it. Kamianets-Podilskyi is in Khmelnytskyi oblast and is served by **AT Khmelnytskoblenergo** (its own Kamianets-Podilskyi РЕМ), with the same 12 subqueues and the same schedule as the rest of the oblast. So the region is the whole oblast, one button «Хмельницька»; the city is just a settlement in its catalogue (`id 25601`, «м. Кам'янець-Подільський (Кам’янець-Подільська громада)»).

Short version: everything is on `hoe.com.ua`, open, no Cloudflare. The address → subqueue lookup is a small public JSON + HTML API. The schedule is **only prose** in a news post per day, with updates stacked on top, sometimes as "additional hours". Closer to Lviv than to Volyn, but the schedule parser is the hard part.

## Sources

| Source | Usable? | Why |
|---|---|---|
| `hoe.com.ua/settlements`, `/streets`, `/houses`, `/shutdown-queues` | yes, catalogue | the site's «Перевірити чергу» form (`/shutdown/queue`) |
| `hoe.com.ua/page/arhiv-grafikiv-pogodinnih-vidkljuchen-2026` | yes, index of days | one link per day «Графік погодинних відключень DD.MM.YYYY» → its post |
| `hoe.com.ua/post/<slug>.html` | yes, schedules | one post per day, prose; slugs are not predictable (`prognoz-gpv-na-24-listopada-.html`, `pogodinni-vidkljuchennja-na-25-listopada.html`) |
| `hoe.com.ua/page/pogodinni-vidkljuchennja` | maybe | the same text as the current day's post; when it flips to tomorrow is unknown |
| `/Content/Uploads/GPV6/xls/Черги_на_відключення_<РЕМ>_23112026.xlsx` | only for checks | address → subqueue for each of 6 РЕМ (Kamianets-Podilskyi: 4569 rows, `settlement, street, "1, 10, 11а…", "1.1. підчерга"`); the date in the name changes on refresh |
| `poweron.hoe.com.ua`, `api.hoe.com.ua` | no | wildcard DNS to the same host, no API like Ternopil's |

## Server access

From the Mac (2026-11-27, honest User-Agent, 1 request/second): every endpoint above answers 200, no challenge.

From the production VM (Oracle, Stockholm), 2026-11-27: `/settlements/?term=Хмель` answered **200** with JSON, `/page/pogodinni-vidkljuchennja` **200**. No Mac export like Volyn.

```bash
ssh ubuntu@<server> 'curl -s -A "poweron-bot/0.18 (personal use)" -H "X-Requested-With: XMLHttpRequest" -w "\n%{http_code}\n" "https://hoe.com.ua/settlements/?term=%D0%A5%D0%BC%D0%B5%D0%BB%D1%8C"'
```

## Catalogue

| Call | Answer | Notes |
|---|---|---|
| `GET /settlements/?term=` | `[{id, text}]` | search only, empty term → `[]`, **at most 10**; text carries the hromada |
| `GET /streets/{settlementId}?term=` | `[{id, text}]` | search only, one letter is enough, **at most 30** |
| `GET /houses/{streetId}` | `["1", "2", "12а", "15А", …]` | the whole list, no cap seen; includes houses with no subqueue |
| `POST /shutdown-queues` `streetId=&house=` | HTML | «…ваша адреса відноситься до підчерги: <strong>4.1, 5.1</strong>»; `-` when the house is in no subqueue; a second line for the ГАВ queue (empty so far) |

- All four calls need `X-Requested-With: XMLHttpRequest` (what jQuery sends); without it the site answers its 404 page, from the Mac and the server alike.
- Checked on вул. Шевченка, Kamianets-Podilskyi (street `329329`): 45 → `3.1`, 19 → `4.1`, 21 → `4.1, 5.1` (two connections, the xlsx agrees), 1 / 12 / 27 → `-` (not in the xlsx either).
- A house is identified by its text, not an id; the daily queue re-check needs `streetId` + house text.
- Names: «вул. Шевченка», «вул. Тараса Шевченка» and «пров. Шевченка» are separate streets in one city.

## Schedule text

The day's post, newest block on top, blocks separated by `<hr />`. Surveyed 20 posts of 07–27.11.2026; every subqueue line matched one shape:

```
Підчерга 1.1 – 06:00-08:00; 11:00-14:00; 17:00-20:00; 22:00-24:00.
Підчерга 2.1 - 20:00-22:00.
Підчерга 2.1 – вимкнень немає.
Підчерга 5.2 – без відключень.
```

- 12 subqueues `1.1` … `6.2`; en dash or hyphen; intervals `HH:MM-HH:MM` joined by «; »; the day ends `24:00`.
- Times on `:00` and `:30` only (07:30, 09:30, 10:30 seen), so it fits the 48 slots. Only OFF and ON, no switching state.
- Block headers (all prose, from «За розпорядженням НЕК «Укренерго»…»):
  1. first schedule: «DD.MM.YYYY р. на Хмельниччині будуть застосовані графіки погодинних відключень (ГПВ)» + «Години відсутності електроенергії:» + a full list;
  2. full replacement: «оновлено графік … на 20 листопада (оновлено з 10:30)», also «(оновлено 23:35)», «(оновлено, 12:30)», «(16:00)», «(з 17:30)», «(оновлено о 23:00, 15.11.2026)», or no time at all; on 20.11 a replacement «з 10:30» still lists the morning intervals, so a full list is the whole day;
  3. additional hours: «Додаткові (also «Додатково») години відсутності електроенергії:» + only the changed subqueues, to be added to the full list below it.
- A full list may leave subqueues out (15.11: 8 and 10 of 12), which reads as no outages for them: 15.11's lists agree only that way.
- Up to 5 blocks a day (20.11). Updates come the evening before (23:00–23:40) and during the day.
- Blocks per post, newest first: mostly `full12`; `add1 full12` (27.11), `add2 add3 full12` (24.11: two «Додаткові» stacked), `add2 full12 full12 full12` (23.11), `full12 full10 full8` (15.11).
- Rule that fits all 20 posts: take the newest full list (missing subqueues ON), then OR in every «Додаткові» block above it. The only thing telling the two kinds apart is the word «Додатков…». Anything else in a block is an `ApiSchemaError`.
- No post for a day: 01–06.11 have none (no ГПВ then). For tomorrow it means "not published yet"; for today it most likely means no outages, unconfirmed.

## Probe

`scripts/probe_khmelnytskyi.py`: stdlib only, sequential, at most 1 request/second, one public street (вул. Шевченка, Kamianets-Podilskyi). Reads the archive index, sorts the posts of 15, 20, 24, 27.11 and today into blocks, flags any subqueue line of an unknown shape, walks the lookup. Fixtures `hoe_*` (only `<main>` of each page); `--dry` saves nothing; extra dates as arguments.

## Decisions (owner, 2026-11-27)

1. **Build with the rule above now**: the newest full list plus every «Додаткові» block above it. A block of any other shape is an `ApiSchemaError`, so the admin hears about it.
2. **No post for today means unknown**, not "no outages": the last version stays, nothing is pushed.
3. **House: typed as text or picked from buttons.** The exact screen goes in the build plan.

## Still open

- The rule is read from 20 posts, not stated by the oblenergo. A block that takes hours away without being a full list, or a «Додаткові» block meant as a replacement, would break it silently.
- When tomorrow's post appears and whether `pogodinni-vidkljuchennja` flips to it. The archive index makes that page unnecessary; a poll costs index + 1–2 posts (3 requests).

## Fit with the code

- One provider and region, `hoe`, keys `hoe:4.1`. No migration.
- `adapters/hoe_api/`: `ScheduleSource` (archive index → posts → parser) and a `StreetSearchCatalogSource` (settlements and streets are search-only, houses listed), through `PacedHttp`.
- No planned works, no current outages, no `remind_exact` at first. The site has «Відключення за адресою» and «Актуальні відключення» pages for later.
- Region buttons stay alphabetical: «Хмельницька» goes last.

## How it is built

- `adapters/hoe_api/schedule.py`: `parse_archive` (day → its entries' links) and `parse_post` (the rule above: the newest full list, a subqueue left out is ON, plus every «Додаткові» block above it). A subqueue line of any other shape, an interval off the 30-minute grid, a subqueue twice in a block, or a block above the newest list that is neither kind (say «графік скасовано») is an `ApiSchemaError`. «22:00-00:00» ends at midnight.
- `adapters/hoe_api/client.py`: `HoeClient` is the schedule source and a `StreetSearchCatalogSource`.
  - Schedules: the year's archive page and the news list (`/post/novini-kompaniji`) as the index of days, then the posts of today and tomorrow, cached 60 s, so a poll costs 3–4 requests.
  - Why both indexes: the archive is filed by hand hours after a post (27.11 at 20:17 the 28.11 post was out and in the news list, not in the archive), while the news list titles vary («Прогноз ГПВ на 28 листопада», «Погодинні відключення на 25 листопада»). A missing archive page (a new year's) is logged, not an error.
  - A post must announce the day it is filed under (the first «За розпорядженням …» line names it, «27.11.2026» or «27 листопада»); otherwise an `ApiSchemaError`.
  - The «Погодинні відключення» page is not read: on 27.11 it still showed 26.11 and had dropped that day's 12:30 addition that the post kept. (0.19.0 used it as a check against the archive, which alerted on the archive's lag.) A day with no entry gives no schedule (the last version stays). A day with several entries or a picture instead of a post is an `ApiSchemaError`. A broken today fails the poll (the admin hears of it); a broken tomorrow is only logged, so it does not hide today.
  - The posts carry no publication time, so each subqueue's day dates from when the worker first saw its codes (in memory: a restart dates the current days anew).
  - Catalogue: settlements and streets searched live (the hromada split off into `otg_name`), a street's houses listed (cached 24 h, ids are crc32 of the name), the queues asked once a house is picked (`POST /shutdown-queues`; «-» or an empty value is no queue). The search term loses the type prefix and Latin look-alikes and keeps the longest piece between apostrophes, since the site only knows its own apostrophe.
- `StreetSearchCatalogSource` in core: `Catalog` searches settlements and streets live and lists houses; `/add` shows them as buttons and takes a typed number too, like Ternopil.
- `PacedHttp.post` sends a form POST, paced and retried like a GET.
- Telegram: «Хмельницька» last among the regions; the site link is the «Погодинні відключення» page, the «⚡ Немає світла? Аварійні» button opens `hoe.com.ua/shutdown/all`.
- No migration (keys `hoe:4.1`), no switching state, no planned works, no current-outage line, no `remind_exact`.
- Checked live through the real client on 27.11: Kamianets-Podilskyi, вул. Шевченка 21 → `hoe:4.1`, `hoe:5.1`; 45 → `hoe:3.1`; 1 → none; today's 4.1 and 6.1 match the post (6.1 with its added hour).
- Known limits:
  - The rule is read from the posts, not stated by the oblenergo; a new kind of block fails loudly, but a «Додаткові» block meant as a replacement would be read wrong.
  - A day's post missing from both the archive and the news list (a reworded title and a slow archive) looks like no post: no alert, the last version stays.
  - At most 10 settlements and 30 streets per search: a short query may not show the wanted one; typing more narrows it.

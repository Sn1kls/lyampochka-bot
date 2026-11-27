"""Live probe of the YASNO API for Dnipropetrovsk oblast (docs/dnipro-notes.md).

Reads both distribution operators' schedules (DTEK DnEM, CEK) and walks the address ->
group lookup for one public address of each, prints the shapes and saves fixtures to
tests/fixtures/. Stdlib only, sequential, at most one request per second.

    uv run python scripts/probe_dnipro.py          # probe and save fixtures
    uv run python scripts/probe_dnipro.py --dry    # probe only
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

API = "https://app.yasno.ua/api/blackout-service/public/shutdowns"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "poweron-bot/0.16 (personal use)"
REGION_ID = 3  # «Дніпро» in YASNO's region list
DNEM, CEK = 301, 303
# Public addresses: Dnipro, the central avenue for DnEM; the first CEK street found.
CITY_QUERY, DNEM_STREET_QUERY, CEK_STREET_QUERY = "Дніпро", "Яворницького Дмитра", "Кедр"
_last_call = 0.0
save_fixtures = "--dry" not in sys.argv


def get(path: str, **params: Any) -> Any:
    global _last_call
    time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_call)))
    url = f"{API}/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, raw = response.status, response.read()
            kind = response.headers.get("content-type", "")
    except urllib.error.HTTPError as error:
        status, raw, kind = error.code, error.read(), ""
    finally:
        _last_call = time.monotonic()
    print(f"  {status} {len(raw)}B {url}")
    if status != 200 or "json" not in kind:
        # An Incapsula challenge answers 200 with HTML, so the type is checked too.
        sys.exit(f"unexpected answer {status} {kind!r}: {raw[:300]!r}")
    return json.loads(raw)


def save(name: str, data: Any) -> None:
    if not save_fixtures:
        return
    path = FIXTURES / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  saved {path.relative_to(FIXTURES.parent.parent)}")


def describe_schedule(dso: int, data: dict[str, Any]) -> None:
    print(f"  dso {dso}: {len(data)} groups {sorted(data, key=lambda key: float(key))}")
    for day in ("today", "tomorrow"):
        statuses = Counter(str(group.get(day, {}).get("status")) for group in data.values())
        dates = {group.get(day, {}).get("date") for group in data.values()}
        print(f"    {day}: {dict(statuses)} {dates}")
    types = Counter(
        slot["type"]
        for group in data.values()
        for day in ("today", "tomorrow")
        for slot in group.get(day, {}).get("slots", [])
    )
    off_grid = [
        slot
        for group in data.values()
        for day in ("today", "tomorrow")
        for slot in group.get(day, {}).get("slots", [])
        if slot["start"] % 30 or slot["end"] % 30
    ]
    print(f"    slot types {dict(types)}, off the 30-min grid: {len(off_grid)}")


def first(items: list[dict[str, Any]], what: str) -> dict[str, Any]:
    if not items:
        sys.exit(f"no {what} found")
    return items[0]


def address(dso: int, street_query: str) -> None:
    cities = get("addresses/v2/cities", regionId=REGION_ID, dsoId=dso, query=CITY_QUERY)
    city = next(item for item in cities if item["value"].endswith(CITY_QUERY))
    streets = get(
        "addresses/v2/streets",
        regionId=REGION_ID,
        dsoId=dso,
        cityId=city["id"],
        query=street_query,
    )
    street = first(streets, "street")
    houses = get(
        "addresses/v2/houses",
        regionId=REGION_ID,
        dsoId=dso,
        cityId=city["id"],
        streetId=street["id"],
        query="",
    )
    house = first(houses, "house")
    group = get(
        "addresses/v2/group",
        regionId=REGION_ID,
        dsoId=dso,
        cityId=city["id"],
        streetId=street["id"],
        houseId=house["id"],
    )
    print(f"  {city['value']}, {street['value']} {house['value']} -> {group}")
    print(f"  houses on the street (capped at 20?): {len(houses)}")
    save(f"yasno_streets_{dso}.json", streets)
    save(f"yasno_houses_{dso}.json", houses)
    save(f"yasno_group_{dso}.json", group)


def main() -> None:
    print("regions")
    regions = get("addresses/v2/regions")
    save("yasno_regions.json", regions)
    for dso in (DNEM, CEK):
        print(f"schedule {dso}")
        schedule = get(f"regions/{REGION_ID}/dsos/{dso}/planned-outages")
        describe_schedule(dso, schedule)
        save(f"yasno_planned_outages_{dso}.json", schedule)
    print("CEK settlements")
    cek_cities = get("addresses/v2/cities", regionId=REGION_ID, dsoId=CEK, query="")
    print(f"  {[city['value'] for city in cek_cities]}")
    save("yasno_cities_303.json", cek_cities)
    print("address DnEM")
    address(DNEM, DNEM_STREET_QUERY)
    print("address CEK")
    address(CEK, CEK_STREET_QUERY)


if __name__ == "__main__":
    main()

"""Live probe of the Lvivoblenergo APIs (docs/lviv-notes.md).

Reads today's and tomorrow's schedule text and the address -> queue lookup for one
public address, prints their shape, and saves fixtures to tests/fixtures/.
Stdlib only, sequential, at most one request per second.
"""

import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

CONTENT_API = "https://api.loe.lviv.ua/api"
POWER_API = "https://power-api.loe.lviv.ua/api"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "poweron-bot/0.10 (personal use)"
# Menu items of the "photo-grafic" menu, as the site reads them.
TODAY_ITEM, TOMORROW_ITEM = 238, 256
# Public address: Lviv, пл. Ринок (the site's own street list).
LVIV_CITY_ID, RYNOK_STREET_ID = 693, 31831
_last_call = 0.0


def get(url: str) -> Any:
    global _last_call
    time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_call)))
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/ld+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, raw = response.status, response.read()
            cache = response.headers.get("cf-cache-status")
    except urllib.error.HTTPError as error:
        status, raw, cache = error.code, error.read(), None
    finally:
        _last_call = time.monotonic()
    print(f"  {status} {len(raw)}B cf={cache} {url}")
    if status != 200:
        sys.exit(f"unexpected HTTP {status}: {raw[:300]!r}")
    return json.loads(raw)


def save(name: str, data: Any) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"  saved {path.relative_to(FIXTURES.parent.parent)}")


def members(data: Any) -> list[Any]:
    """Some endpoints answer a hydra collection, others a bare list."""
    if isinstance(data, list):
        print("  (bare list)")
        return data
    return data.get("hydra:member") or []


def main() -> None:
    print("schedule text")
    for name, item_id in (("today", TODAY_ITEM), ("tomorrow", TOMORROW_ITEM)):
        item = get(f"{CONTENT_API}/menu_items/{item_id}")
        print(f"  {name}: keys={sorted(item)} name={item.get('name')!r}")
        print(f"  rawHtml={item.get('rawHtml')!r}")
        save(f"loe_menu_item_{name}.json", item)

    print("groups menu")
    groups = get(f"{CONTENT_API}/menus?page=1&type=power-group&jsonld=1")
    for menu in members(groups):
        print(f"  {[(entry['name'], entry.get('slug')) for entry in menu['menuItems']]}")

    print("catalogue")
    otgs = members(get(f"{POWER_API}/pw_otgs?pagination=false"))
    cities = members(get(f"{POWER_API}/pw_cities?pagination=false&otg.id="))
    streets = members(get(f"{POWER_API}/pw_streets?pagination=false&city.id={LVIV_CITY_ID}"))
    print(f"  otgs={len(otgs)} cities={len(cities)} lviv streets={len(streets)}")
    print(
        f"  otg keys={sorted(otgs[0])} city keys={sorted(cities[0])} street keys={sorted(streets[0])}"
    )

    print("address -> queue")
    accounts = members(
        get(
            f"{POWER_API}/pw_accounts?pagination=false"
            f"&city.id={LVIV_CITY_ID}&street.id={RYNOK_STREET_ID}"
        )
    )
    print(f"  rows={len(accounts)} keys={sorted(accounts[0]) if accounts else []}")
    per_building = Counter(row.get("buildingName") for row in accounts)
    print(
        f"  buildings={len(per_building)} max rows per building={max(per_building.values(), default=0)}"
    )
    queues: dict[str, Counter[str]] = {}
    for row in accounts:
        queues.setdefault(row["buildingName"], Counter())[row["chergGpv"]] += 1
    mixed = {name: dict(found) for name, found in queues.items() if len(found) > 1}
    print(f"  buildings with several queues: {len(mixed)} of {len(queues)}")
    for name, found in list(mixed.items())[:8]:
        print(f"    {name!r}: {found}")
    print(f"  building names: {sorted(queues)}")
    # The fixture keeps every row of a few buildings, mixed ones included.
    keep = set(list(mixed)[:2]) | set(sorted(queues)[:3])
    save("loe_pw_accounts_rynok.json", [row for row in accounts if row["buildingName"] in keep])


if __name__ == "__main__":
    main()

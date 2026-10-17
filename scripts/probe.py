"""Phase 0 live probe of the unofficial toe API (SPEC §2.3).

Calls the endpoints for one known address, saves raw responses to
tests/fixtures/ and prints what each open question needs. Stdlib only,
sequential, at most one request per second.
"""

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from itertools import count, groupby
from pathlib import Path
from zoneinfo import ZoneInfo

API = os.environ.get("API_BASE", "https://api-poweron.toe.com.ua/api")
CITY_ID, STREET_ID = 1032, 9985  # Ternopil, vul. Sadova (SPEC §12)
KYIV = ZoneInfo("Europe/Kyiv")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
# Site legend: "1" = вимкнення, "10" = час на перемикання, anything else = подача.
STATES = {"0": "ON", "1": "OFF", "10": "SWITCHING"}


def contact() -> str:
    if value := os.environ.get("CONTACT"):
        return value
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("CONTACT="):
            return line.split("=", 1)[1].strip().strip("\"'") or "n/a"
    return "n/a"


USER_AGENT = f"poweron-bot/0.0 (personal use; contact: {contact()})"
_last_call = 0.0


def get(
    path: str,
    params: dict[str, object] | list[tuple[str, object]],
    headers=None,
):
    """GET with a 1 req/s floor. Returns (status, headers, parsed JSON or text)."""
    global _last_call
    time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_call)))
    url = f"{API}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            status, hdrs, raw = resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        status, hdrs, raw = e.code, dict(e.headers), e.read()
    finally:
        _last_call = time.monotonic()
    try:
        body = json.loads(raw)
    except ValueError:
        body = raw.decode("utf-8", "replace")[:500]
    print(f"  {status} cf={hdrs.get('cf-cache-status')} age={hdrs.get('Age')} GET {path} {params}")
    if status != 200:  # stop before an error page overwrites a recorded fixture
        sys.exit(f"unexpected HTTP {status}: {body!r}")
    return status, hdrs, body


def save(name: str, body: object) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n")


def members(body: object) -> list:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        return body.get("hydra:member") or []
    return []


def site_range(now: datetime) -> tuple[str, str]:
    """after/before exactly as the site client builds them (local date, fake +00:00)."""
    after = (now - timedelta(days=1)).strftime("%Y-%m-%dT12:00:00+00:00")
    before = (now + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+00:00")
    return after, before


def addr_key(city: int, street: int, building: str) -> tuple[str, dict[str, str]]:
    """(`time` param, X-debug-key header) for an address, as the site builds them."""
    p = f"{city}/{street}/{building}"
    return p.replace("/", ""), {"X-debug-key": base64.b64encode(p.encode()).decode()}


def intervals(times: dict[str, str]) -> list[str]:
    def state(slot: str) -> str:
        return STATES.get(times[slot], f"UNKNOWN({times[slot]})")

    if not times:
        return []
    runs = [(next(g), st) for st, g in groupby(sorted(times), key=state)]
    ends = [s for s, _ in runs[1:]] + ["24:00"]
    return [f"{s}-{e} {st}" for (s, st), e in zip(runs, ends, strict=True)]


def summary(body: object) -> list[tuple[object, object, list]]:
    return [
        (m.get("dateGraph"), m.get("dateCreate"), sorted(m.get("dataJson", {})))
        for m in members(body)
    ]


def main() -> int:
    now = datetime.now(KYIV)
    print(f"now {now.isoformat()}  UA: {USER_AGENT}")

    print("[catalog]")
    _, _, cities = get("/pw_cities", {"pagination": "false"})
    save("pw_cities.json", cities)
    print(f"  cities: {type(cities).__name__}, {len(members(cities))} items")
    _, _, streets = get("/pw_streets", {"pagination": "false", "city.id": CITY_ID})
    save(f"pw_streets_{CITY_ID}.json", streets)
    print(f"  streets: {type(streets).__name__}, {len(members(streets))} items")
    _, _, buildings = get("/pw-accounts/building-names", {"cityId": CITY_ID, "streetId": STREET_ID})
    save(f"building_names_{CITY_ID}_{STREET_ID}.json", buildings)
    names = buildings["buildingNames"]
    values = Counter(repr(b.get("chergGpv")) for b in names)
    print(f"  buildings: {len(names)}, chergGpv values: {values}")

    real = [b for b in names if b.get("chergGpv") not in (None, "", "Не входить")]
    if not real:
        sys.exit("no building with a real chergGpv on the probed street")
    target = next((b for b in real if b["buildingName"] == "1"), real[0])
    group = target["chergGpv"]
    other = next((b for b in names if b["chergGpv"] == group and b is not target), None)
    our_time, key = addr_key(CITY_ID, STREET_ID, target["buildingName"])
    after, before = site_range(now)
    base = {"after": after, "before": before, "time": our_time}
    print(f"[a_gpv_g] building {target['buildingName']!r} group {group!r} {after} .. {before}")

    # Cloudflare caches /a_gpv_g by URL, so every experiment below gets its own URL
    # by moving `before` by a few seconds (same day, same result window).
    # Start from the clock so reruns within the 2 h edge TTL don't reuse a cached URL.
    # ponytail: collides only for runs started < ~20 s apart
    bust = count(int(time.time()) % 3000 + 1)

    def fresh(params: dict[str, object]) -> dict[str, object]:
        return {
            **params,
            "before": before.replace(
                "T00:00:00", "T00:{:02d}:{:02d}".format(*divmod(next(bust), 60))
            ),
        }

    # Baseline from the origin (busted URL); the plain site URL may be stale at the edge.
    _, hdrs, sched = get("/a_gpv_g", fresh({**base, "group": group}), key)
    print(
        f"  headers: { {k: v for k, v in hdrs.items() if k.lower().startswith(('x-', 'retry', 'ratelimit', 'cf-', 'server', 'cache'))} }"
    )
    print(f"  members: {summary(sched)}")
    if not members(sched):
        sys.exit("baseline schedule is empty, comparisons would be meaningless; rerun later")
    save(f"a_gpv_g_{group}_{now:%Y-%m-%d}.json", sched)
    for m in members(sched):
        for sub, data in m["dataJson"].items():
            print(f"  {m['dateGraph']} {sub}: {', '.join(intervals(data['times']))}")
            print(
                f"    distinct slot values: {sorted(set(data['times'].values()))}, slots: {len(data['times'])}"
            )

    def same(label: str, body: object) -> None:
        print(
            f"  {label}: {'SAME' if members(body) == members(sched) else 'DIFFERENT'} {summary(body)}"
        )

    print("[§2.3.3 X-debug-key / time / group]")
    same(
        "group[] like axios",
        get("/a_gpv_g", [*fresh(base).items(), ("group[]", group)], key)[2],
    )
    _, _, no_key = get("/a_gpv_g", fresh({**base, "group": group}))
    save("a_gpv_g_no_key.json", no_key)
    same("no X-debug-key", no_key)
    same(
        "key only, no time",
        get("/a_gpv_g", fresh({"after": after, "group": group}), key)[2],
    )
    if other:
        otime, okey = addr_key(CITY_ID, STREET_ID, other["buildingName"])
        same(
            "other building, same group",
            get("/a_gpv_g", fresh({**base, "time": otime, "group": group}), okey)[2],
        )
    alt = "1.1" if group != "1.1" else "2.1"
    same(
        f"group {alt} for this address",
        get("/a_gpv_g", fresh({**base, "group": alt}), key)[2],
    )
    same("no group", get("/a_gpv_g", fresh(base), key)[2])

    print("[§2.3.3 another subqueue: who decides, time or key?]")
    found = None
    for street in (9982, 9986):  # Mykulynetska, Festyvalna
        _, _, other_b = get("/pw-accounts/building-names", {"cityId": CITY_ID, "streetId": street})
        found = next(
            (
                (street, b)
                for b in other_b["buildingNames"]
                if b.get("chergGpv") not in (group, "Не входить", "", None)
            ),
            None,
        )
        if found:
            break
    if found:
        street, b = found
        ftime, fkey = addr_key(CITY_ID, street, b["buildingName"])
        print(f"  other address group {b['chergGpv']!r}")
        _, _, own = get("/a_gpv_g", fresh({**base, "time": ftime, "group": b["chergGpv"]}), fkey)
        save(f"a_gpv_g_{b['chergGpv']}_{now:%Y-%m-%d}.json", own)
        print(f"  its time + its key: {summary(own)}")
        print(
            f"  our time + its key: {summary(get('/a_gpv_g', fresh({**base, 'group': group}), fkey)[2])}"
        )
        print(
            f"  its time + our key: {summary(get('/a_gpv_g', fresh({**base, 'time': ftime, 'group': group}), key)[2])}"
        )
    else:
        print("  SKIPPED: no building in another subqueue on the probed streets")

    print("[§2.3.6 'Не входить' building]")
    excluded = next((b for b in names if b["chergGpv"] == "Не входить"), None)
    if excluded:
        etime, ekey = addr_key(CITY_ID, STREET_ID, excluded["buildingName"])
        _, _, ebody = get("/a_gpv_g", fresh({**base, "time": etime, "group": "Не входить"}), ekey)
        save("a_gpv_g_not_included.json", ebody)
        print(f"  building {excluded['buildingName']!r}: {summary(ebody)}")
    else:
        print("  SKIPPED: no «Не входить» building on this street")

    print("[§2.3.4 caching]")
    _, h, edge = get("/a_gpv_g", {**base, "group": group}, key)
    same(f"plain site URL vs origin (Cache-Control {h.get('Cache-Control')})", edge)
    get("/a_gpv_g", {**base, "group": group}, {**key, "Cache-Control": "no-cache"})
    print("  ^ same URL with request Cache-Control: no-cache")

    print("[§2.3.4 User-Agent]")
    plain_ua = {
        **key,
        "User-Agent": f"Python-urllib/{sys.version_info[0]}.{sys.version_info[1]}",
    }
    status, _, body = get("/a_gpv_g", fresh({**base, "group": group}), plain_ua)
    print(
        f"  default urllib UA -> {status}, {'SAME' if members(body) == members(sched) else body if isinstance(body, str) else 'DIFFERENT'}"
    )

    print("[§2.3.5 ranges]")
    far = now + timedelta(days=30)
    _, _, empty = get(
        "/a_gpv_g",
        {
            **base,
            "group": group,
            "after": site_range(far)[0],
            "before": site_range(far)[1],
        },
        key,
    )
    save("a_gpv_g_empty.json", empty)
    print(f"  +30 days: {type(empty).__name__} {summary(empty)}")
    _, _, past = get(
        "/a_gpv_g",
        {**base, "group": group, "after": site_range(now - timedelta(days=7))[0]},
        key,
    )
    print(f"  last 7 days: {summary(past)}")

    print("[phase 5 sample]")
    _, _, planned = get(
        "/pw_accident_planeds",
        {"page": 1, "otg.id": "", "city.id": CITY_ID, "street.id": STREET_ID},
    )
    save(f"pw_accident_planeds_{CITY_ID}_{STREET_ID}.json", planned)
    print(f"  planned works: {len(members(planned))}")
    return 0


def probe_building(city_id: int, street_id: int, building_name: str) -> int:
    """Print what the API says about one building; saves nothing (addresses are personal)."""
    _, _, names = get("/pw-accounts/building-names", {"cityId": city_id, "streetId": street_id})
    rows = [row for row in names["buildingNames"] if row["buildingName"] == building_name]
    print(f"  building-names rows for {building_name!r}: {rows}")
    params = {"cityId": city_id, "streetId": street_id, "buildingNames": building_name}
    _, _, groups = get("/pw-accounts/building-groups", params)
    print(f"  building-groups: {groups}")
    after, before = site_range(datetime.now(KYIV))
    unique_before = before.replace(
        "T00:00:00", f"T00:{int(time.time()) % 3600 // 60:02d}:{int(time.time()) % 60:02d}"
    )
    address_time, key = addr_key(city_id, street_id, building_name)
    params = {
        "after": after,
        "before": unique_before,
        "time": address_time,
        "group": rows[0]["chergGpv"],
    }
    _, _, schedule = get("/a_gpv_g", params, key)
    print(
        f"  a_gpv_g dataJson keys per day: {[(m['dateGraph'], sorted(m['dataJson'])) for m in members(schedule)]}"
    )
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["building"]:
        sys.exit(probe_building(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]))
    sys.exit(main())

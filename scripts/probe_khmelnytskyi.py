"""Live probe of hoe.com.ua for Khmelnytskyi oblast (docs/khmelnytskyi-notes.md).

Reads the schedule archive index and a few days' posts, sorts each post into blocks
(full list or «Додаткові години»), walks the address -> subqueue lookup for one public
street in Kamianets-Podilskyi, and saves fixtures to tests/fixtures/. Stdlib only,
sequential, at most one request per second.

    uv run python scripts/probe_khmelnytskyi.py               # probe and save fixtures
    uv run python scripts/probe_khmelnytskyi.py --dry         # probe only
    uv run python scripts/probe_khmelnytskyi.py 28.11.2026    # also these days' posts
"""

import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SITE = "https://hoe.com.ua"
ARCHIVE = f"{SITE}/page/arhiv-grafikiv-pogodinnih-vidkljuchen-2026"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "poweron-bot/0.18 (personal use)"
# The site's lookup answers its 404 page unless the request looks like jQuery's.
AJAX = {"X-Requested-With": "XMLHttpRequest"}
# Days whose posts show every block shape seen in November 2026 (notes, "Schedule text").
FIXTURE_DAYS = {
    "15.11.2026": "partial",  # full lists that leave subqueues out
    "20.11.2026": "five_updates",
    "24.11.2026": "two_additions",  # two «Додаткові» blocks stacked on one full list
    "27.11.2026": "addition",
}
# Public address: Kamianets-Podilskyi, вул. Шевченка; 21 has two connections, 1 has none.
SETTLEMENT_QUERY, STREET_QUERY, STREET_NAME = "Кам'янець", "Шевч", "вул. Шевченка"
HOUSES = ("21", "45", "1")
QUEUE_LINE = re.compile(
    r"Підчерга [1-6]\.[12] [–-] "
    r"(\d\d:\d\d-\d\d:\d\d(; \d\d:\d\d-\d\d:\d\d)*\.?|вимкнень немає\.|без відключень\.)"
)
_last_call = 0.0
save_fixtures = "--dry" not in sys.argv


def request(url: str, data: dict[str, str] | None = None, ajax: bool = False) -> str:
    global _last_call
    time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_call)))
    headers = {"User-Agent": USER_AGENT} | (AJAX if ajax else {})
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, data=body, headers=headers), timeout=30
        ) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    finally:
        _last_call = time.monotonic()
    print(f"  {status} {len(raw)}B {urllib.parse.unquote(url)}")
    if status != 200:
        sys.exit(f"unexpected answer {status}: {raw[:300]!r}")
    return raw.decode("utf-8")


def get_json(path: str, **params: str) -> Any:
    url = f"{SITE}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    return json.loads(request(url, ajax=True))


def main_part(page: str) -> str:
    """The page's <main>, without the menu, sidebar and scripts around it."""
    start, end = page.find("<main"), page.find("</main>")
    if start < 0 or end < 0:
        sys.exit("no <main> in the page")
    return page[start : end + len("</main>")] + "\n"


def save(name: str, text: str) -> None:
    if not save_fixtures:
        return
    path = FIXTURES / name
    path.write_text(text, encoding="utf-8")
    print(f"  saved {path.relative_to(FIXTURES.parent.parent)}")


def plain_lines(fragment: str) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]+>", "\n", fragment))
    return [line for line in (re.sub(r"\s+", " ", raw).strip() for raw in text.split("\n")) if line]


def describe_post(page: str) -> None:
    post = page[page.find('<div class="post">') :]
    kinds = []
    for block in re.split(r"<hr\s*/?>", post):
        lines = [line for line in plain_lines(block) if line.startswith("Підчерга")]
        if not lines:
            continue
        odd = [line for line in lines if not QUEUE_LINE.fullmatch(line)]
        kind = "add" if "Додатков" in block else "full"
        kinds.append(f"{kind}{len(lines)}")
        for line in odd:
            print(f"    UNKNOWN LINE: {line}")
    print(f"    blocks, newest first: {' '.join(kinds) or 'none'}")


def schedules(extra_days: list[str]) -> None:
    print("archive index")
    archive = request(ARCHIVE)
    days = re.findall(
        r'href="(https://hoe\.com\.ua/post/[^"]+)"[^>]*>\s*Графік погодинних відключень '
        r"(\d\d\.\d\d\.\d{4})([^<]*)<",
        archive,
    )
    print(f"  {len(days)} entries, newest: {[day + note for _, day, note in days[:5]]}")
    save("hoe_archive.html", main_part(archive))
    today = datetime.now(ZoneInfo("Europe/Kyiv")).strftime("%d.%m.%Y")
    wanted = {day: "" for day in [today, *extra_days]} | FIXTURE_DAYS
    for day, fixture in wanted.items():
        url = next((url for url, title, _ in days if title == day), None)
        print(f"post {day}")
        if url is None:
            print("    no post in the archive")
            continue
        page = request(url)
        describe_post(page)
        if fixture:
            save(f"hoe_post_{fixture}.html", main_part(page))


def address() -> None:
    print("address")
    settlements = get_json("settlements/", term=SETTLEMENT_QUERY)
    settlement = settlements[0]
    streets = get_json(f"streets/{settlement['id']}", term=STREET_QUERY)
    street = next(item for item in streets if item["text"] == STREET_NAME)
    houses = get_json(f"houses/{street['id']}")
    print(f"  {settlement['text']}, {street['text']}: {len(houses)} houses")
    save("hoe_settlements.json", json.dumps(settlements, ensure_ascii=False, indent=1) + "\n")
    save("hoe_streets.json", json.dumps(streets, ensure_ascii=False, indent=1) + "\n")
    save("hoe_houses.json", json.dumps(houses, ensure_ascii=False, indent=1) + "\n")
    for house in HOUSES:
        answer = request(
            f"{SITE}/shutdown-queues", {"streetId": str(street["id"]), "house": house}, ajax=True
        )
        queues = re.search(r"підчерги:\s*<strong>([^<]*)</strong>", answer)
        print(f"    {house} -> {queues.group(1) if queues else 'UNKNOWN ANSWER'}")
        save(f"hoe_queues_{house}.html", answer)


def main() -> None:
    schedules([arg for arg in sys.argv[1:] if not arg.startswith("--")])
    address()


if __name__ == "__main__":
    main()

"""Live probe of the Volynoblenergo site forms (docs/volyn-notes.md).

Asks the queue lookup and the schedule search, saves raw HTML to tests/fixtures/
and prints the markers the adapter relies on. Stdlib only, sequential,
at most one request per second. Only public street names, never a personal address.
"""

import http.cookiejar
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SITE = "https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni"
KYIV = ZoneInfo("Europe/Kyiv")
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
USER_AGENT = "poweron-bot/0.2 (personal use)"
MARKERS = {
    "not_found": "Вибраної адреси у графіках не знайдено",
    "filter": "Фільтр:",
    "back_to_form": "Повернутись до форми пошуку",
    "updated": "Оновлено:",
    "table": "<table",
}
_last_call = 0.0


def request(
    opener: urllib.request.OpenerDirector, path: str, fields: dict[str, str] | None = None
) -> str:
    """GET, or POST when `fields` are given, with a 1 req/s floor."""
    global _last_call
    time.sleep(max(0.0, 1.0 - (time.monotonic() - _last_call)))
    data = None if fields is None else urllib.parse.urlencode(fields).encode()
    try:
        req = urllib.request.Request(
            f"{SITE}/{path}", data=data, headers={"User-Agent": USER_AGENT}
        )
        with opener.open(req, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    finally:
        _last_call = time.monotonic()
    html = raw.decode("utf-8", "replace")
    found = [name for name, marker in MARKERS.items() if marker in html]
    print(f"  {status} len={len(html)} {'POST' if fields else 'GET'} {path} {fields} {found}")
    if status != 200:
        sys.exit(f"unexpected HTTP {status}: {html[:300]!r}")
    return html


def search_schedule(city: str, day: str) -> str:
    """The search needs a PHP session from the form page, and a session serves one search."""
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    request(opener, "hrafik-vidkliuchen/")
    fields = {
        "formGpvDate": day,
        "formCity": city,
        "formStreet": "",
        "searchForm": "searchFromForm",
    }
    return request(opener, "hrafik-vidkliuchen/pagephp.php", fields)


def save(name: str, html: str) -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    (FIXTURES / name).write_text(html)


def main() -> None:
    plain = urllib.request.build_opener()
    today = datetime.now(KYIV).date()

    print("queue lookup")
    for name, city, street in (
        ("kivertsi_nezalezhnosti", "Ківерці", "Незалежності"),
        ("lutsk_lesi_ukrainky", "Луцьк", "Лесі Українки"),
        ("none", "Ківерці", "Неіснуюча"),
    ):
        fields = {"formCity": city, "formStreet": street}
        save(f"voe_cherga_{name}.html", request(plain, "cherga/", fields))

    print("schedule search, one session per search")
    for city, day in (("Луцьк", today), ("Ківерці", today + timedelta(days=1))):
        html = search_schedule(city, f"{day}")
        if MARKERS["not_found"] not in html:
            save(f"voe_gpv_{day}_{'lutsk' if city == 'Луцьк' else 'kivertsi'}.html", html)
            print("  >>> not the 'not found' page: saved for the parser")
    save("voe_gpv_not_found.html", search_schedule("Луцьк", f"{today}"))


if __name__ == "__main__":
    main()

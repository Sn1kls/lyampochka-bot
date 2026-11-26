"""Export the outages going on now in the whole Volyn oblast (emergency and planned).

The page (energy.volyn.ua …/chomu-nemaie-elektropostachannia/) is behind a Cloudflare challenge
for the production server, so this runs every 15 minutes on the owner's Mac and the result is
piped into the bot: see `scripts/sync_volyn_outages.sh`. The site refreshes it every 30 minutes.

The settlement field matches a substring and results are not capped, so one request per vowel
covers every settlement. Stdlib only, sequential, at least 1.5 s between requests.

Output (stdout): JSON `{"rows": [[district, settlement, street, [building, …], kind, start, end,
reason], …]}`; kind is "emergency" or "planned", start and end are Kyiv wall clock
"YYYY-MM-DD HH:MM". Rows that apply the hourly schedule are left out: the bot shows those already.
"""

import json
import re
import sys
import time

from export_volyn_queues import REQUEST_INTERVAL, VOWELS, TableParser, buildings, post

URL = "https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/chomu-nemaie-elektropostachannia/"
USER_AGENT = "poweron-bot (personal use; outages every 15 min)"
HEADER = ["Район", "Нас. пункт", "Вулиця", "Будинок", "Тип", "Причина"]
KINDS = {"Аварійне вимкнення": "emergency", "Планове вимкнення": "planned"}
SCHEDULE_KINDS = {"Застосування ГПВ", "Застосування ГАВ"}
NOTHING_FOUND = "вимкнень не знайдено"
DATE_TIME = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")

Row = tuple[str, str, str, tuple[str, ...], str, str, str, str]


def outage_rows(html: str) -> list[Row]:
    """Emergency and planned rows of one answer; a page that is neither a table nor «not found»
    stops the export, so a changed layout never looks like a quiet oblast."""
    if "Фільтр:" not in html:
        raise SystemExit("the page has no filter line, layout changed?")
    parser = TableParser()
    parser.feed(html)
    table = [row for row in parser.rows if len(row) == len(HEADER) + 1]
    if not table:
        if NOTHING_FOUND not in html:
            raise SystemExit("no table and no «not found» line, layout changed?")
        return []
    if table[0][: len(HEADER)] != HEADER:
        raise SystemExit(f"unexpected table header: {table[0]}")
    rows: list[Row] = []
    for district, settlement, street, cell, kind, reason, dates in table[1:]:
        if kind in SCHEDULE_KINDS:
            continue
        if kind not in KINDS:
            print(f"  skipped an unknown outage type: {kind!r}", file=sys.stderr)
            continue
        start_end = DATE_TIME.findall(dates)
        names = tuple(buildings(cell))
        if len(start_end) != 2:  # e.g. no expected end yet: one odd row must not stop the rest
            print(f"  skipped a row without start and end: {dates!r}", file=sys.stderr)
        elif names:  # a row with only the «<>» placeholder names no building
            row = (district, settlement, street, names, KINDS[kind], *start_end, reason[:256])
            rows.append(row)
    return rows


def main() -> None:
    found: set[Row] = set()
    for vowel in VOWELS:
        found.update(outage_rows(post(URL, {"formCity": vowel, "formStreet": ""}, USER_AGENT)))
        time.sleep(REQUEST_INTERVAL)
    rows = [[*row[:3], list(row[3]), *row[4:]] for row in sorted(found)]
    json.dump({"rows": rows}, sys.stdout, ensure_ascii=False)
    print(f"{len(rows)} outages", file=sys.stderr)


if __name__ == "__main__":
    main()

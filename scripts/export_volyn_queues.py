"""Export Volynoblenergo's address → queue table for the whole oblast.

The site's lookup (energy.volyn.ua …/cherga/) is behind a Cloudflare challenge for the
production server, so this runs weekly from a Ukrainian residential IP (the owner's Mac)
and the result is piped into the bot: see `scripts/sync_volyn_queues.sh`.

Both lookup fields match substrings and results are not capped, so a grid of
"vowel in the settlement" × "vowel in the street" covers every row in ~100 requests.
Stdlib only, sequential, at least 1.5 s between requests.

Output: gzip JSON Lines, one `[district, settlement, street, building, subqueue|null]` per line,
so the bot can import it without holding the whole document in memory.
"""

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

URL = "https://energy.volyn.ua/spozhyvacham/perervy-u-elektropostachanni/cherga/"
USER_AGENT = "poweron-bot (personal use; weekly queue export)"
VOWELS = "аеиіоуяюєї"
HEADER = ["Район", "Нас. пункт", "Вулиця", "Будинок", "Черга у ГПВ", "Черга у ГАВ"]
SUBQUEUE = re.compile(r"^[1-6]\.[12]$")
NUMBER_WITH_LETTER = re.compile(r"(\d+)-?([^\W\d_])")
LATIN_LOOKALIKES = str.maketrans("ABCEHIKMOPTXaceiopx", "АВСЕНІКМОРТХасеіорх")
NOT_INCLUDED = "Не залучено"
REQUEST_INTERVAL = 1.5
ATTEMPTS = 3


class TableParser(HTMLParser):
    """Collects the text of every <td>, row by row."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.rows.append([])
        elif tag == "td":
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def lookup(settlement: str, street: str) -> list[list[str]]:
    body = urllib.parse.urlencode({"formCity": settlement, "formStreet": street}).encode()
    request = urllib.request.Request(URL, data=body, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                html = response.read().decode("utf-8")
            break
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == ATTEMPTS:
                raise
            print(f"  retry {settlement}/{street}: {error}", file=sys.stderr)
            time.sleep(10 * attempt)
    if "Фільтр:" not in html:
        raise SystemExit(f"{settlement}/{street}: the page has no filter line, layout changed?")
    parser = TableParser()
    parser.feed(html)
    rows = [row for row in parser.rows if len(row) == len(HEADER)]
    if rows and rows[0] != HEADER:
        raise SystemExit(f"unexpected table header: {rows[0]}")
    return rows[1:]


def buildings(cell: str) -> list[str]:
    """`16, 19, 22 а, 6-a, <>` → ["16", "19", "22А", "6А"]; `<>` is the site's placeholder."""
    names = (building_name(part) for part in cell.split(","))
    return [name for name in names if name and name != "<>"]


def building_name(raw: str) -> str:
    """One spelling per building: "22 а", "22-а" and "22A" (Latin) all become "22А"."""
    name = "".join(raw.split()).strip("-.")
    if match := NUMBER_WITH_LETTER.fullmatch(name):
        number, letter = match.groups()
        return number + letter.translate(LATIN_LOOKALIKES).upper()
    return name


def subqueue(cell: str) -> str | None:
    if cell == NOT_INCLUDED:
        return None
    if not SUBQUEUE.match(cell):
        raise SystemExit(f"unexpected queue value: {cell!r}")
    return cell


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: export_volyn_queues.py OUTPUT.jsonl.gz")
    found: set[tuple[str, str, str, str, str | None]] = set()
    started = time.monotonic()
    for settlement_vowel in VOWELS:
        for street_vowel in VOWELS:
            rows = lookup(settlement_vowel, street_vowel)
            for district, settlement, street, cell, gpv, _ in rows:
                for building in buildings(cell):
                    found.add((district, settlement, street, building, subqueue(gpv)))
            print(f"  {settlement_vowel}/{street_vowel}: {len(rows)} rows, {len(found)} total")
            time.sleep(REQUEST_INTERVAL)
    rows_out = sorted(found, key=lambda row: (*row[:4], row[4] or ""))
    with gzip.open(sys.argv[1], "wt", encoding="utf-8") as output:
        for row in rows_out:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    settlements = {row[:2] for row in rows_out}
    print(
        f"done in {time.monotonic() - started:.0f} s: {len(rows_out)} buildings, "
        f"{len(settlements)} settlements"
    )


if __name__ == "__main__":
    main()

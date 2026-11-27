"""Khmelnytskyi schedules: a prose post per day, newest block on top (docs/khmelnytskyi-notes.md).

A block is either a full list («Години відсутності електроенергії:», a subqueue left out has
no outages) or «Додаткові години …» added on top of the blocks below it.
"""

import html
import re
from datetime import date, datetime
from urllib.parse import urljoin

from poweron.core.ports import ApiSchemaError

SUBQUEUES = frozenset(f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2))
SLOTS_PER_DAY = 48
OFF, ON = "1", "0"  # toe's raw slot codes

_ARCHIVE_ENTRY = re.compile(
    r'href="([^"]+)"[^>]*>\s*Графік погодинних відключень (\d\d\.\d\d\.\d{4})[^<]*<'
)
_TIME = r"\d\d:[03]0"
_SUBQUEUE_LINE = re.compile(
    rf"Підчерга ([1-6]\.[12]) [–-] (?:(?P<intervals>{_TIME}-{_TIME}(?:; {_TIME}-{_TIME})*)\.?"
    r"|вимкнень немає\.|без відключень\.)"
)
_INTERVAL = re.compile(r"(\d\d):(\d\d)-(\d\d):(\d\d)")
_ADDITION = "Додатков"  # «Додаткові години», once «Додатково години»


def parse_archive(page: str, base_url: str) -> dict[date, list[str]]:
    """Every entry's link by day; a day may have several (in October each update was a picture)."""
    entries: dict[date, list[str]] = {}
    for link, day in _ARCHIVE_ENTRY.findall(page):
        parsed = datetime.strptime(day, "%d.%m.%Y").date()
        entries.setdefault(parsed, []).append(urljoin(base_url, html.unescape(link)))
    if not entries:
        raise ApiSchemaError("hoe archive: no schedule entries")
    return entries


def parse_post(page: str) -> dict[str, str]:
    """Subqueue -> 48 slot codes from 00:00: the newest full list plus the additions above it."""
    start = page.find('<div class="post">')
    if start < 0:
        raise ApiSchemaError("hoe post: no post body")
    additions: list[dict[str, str]] = []
    for block in re.split(r"<hr\s*/?>", page[start:]):
        lines = _lines(block)
        subqueues = _block_subqueues(lines)
        if any(_ADDITION in line for line in lines):
            if not subqueues:
                raise ApiSchemaError("hoe post: additional hours with no subqueue")
            additions.append(subqueues)
        elif subqueues:
            full = {subqueue: subqueues.get(subqueue, ON * SLOTS_PER_DAY) for subqueue in SUBQUEUES}
            for added in additions:
                for subqueue, codes in added.items():
                    full[subqueue] = _merge(full[subqueue], codes)
            return full
        elif lines:
            # Above the newest list: an update that is neither (a cancelled schedule?).
            raise ApiSchemaError(f"hoe post: a block with no subqueues: {lines[0][:100]!r}")
    raise ApiSchemaError("hoe post: no full list of subqueues")


def _lines(block: str) -> list[str]:
    text = html.unescape(re.sub(r"<[^>]+>", "\n", block))
    return [line for line in (" ".join(raw.split()) for raw in text.splitlines()) if line]


def _block_subqueues(lines: list[str]) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in lines:
        if not line.startswith("Підчерга"):
            continue
        match = _SUBQUEUE_LINE.fullmatch(line)
        if match is None:
            raise ApiSchemaError(f"hoe post: unexpected subqueue line {line[:100]!r}")
        subqueue = match.group(1)
        if subqueue in found:
            raise ApiSchemaError(f"hoe post: subqueue {subqueue} twice in a block")
        found[subqueue] = _slots(match.group("intervals") or "")
    return found


def _slots(intervals: str) -> str:
    codes = [ON] * SLOTS_PER_DAY
    for interval in _INTERVAL.finditer(intervals):
        start_hour, start_minute, end_hour, end_minute = map(int, interval.groups())
        start, end = start_hour * 2 + start_minute // 30, end_hour * 2 + end_minute // 30
        if end == 0 < start:  # «22:00-00:00» ends at midnight; «00:00-00:00» is garbage
            end = SLOTS_PER_DAY
        if not 0 <= start < end <= SLOTS_PER_DAY:
            raise ApiSchemaError(f"hoe post: bad interval {interval.group(0)!r}")
        codes[start:end] = [OFF] * (end - start)
    return "".join(codes)


def _merge(base: str, added: str) -> str:
    return "".join(OFF if OFF in pair else ON for pair in zip(base, added, strict=True))

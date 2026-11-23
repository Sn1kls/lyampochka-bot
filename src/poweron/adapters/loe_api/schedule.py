"""The Lviv schedule text: «Група 1.1. Електроенергії немає з 16:30 до 20:00.» per group."""

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime

from poweron.core.domain.models import KYIV
from poweron.core.ports import ApiSchemaError

GROUPS = frozenset(f"{queue}.{half}" for queue in range(1, 7) for half in (1, 2))
SLOTS_PER_DAY = 48
OFF, ON = "1", "0"  # toe's raw slot codes

_DAY = re.compile(r"Графік погодинних відключень на (\d{2}\.\d{2}\.\d{4})")
_PUBLISHED = re.compile(r"Інформація станом на (\d{2}:\d{2}) (\d{2}\.\d{2}\.\d{4})")
_GROUP = re.compile(r"Група (\d\.\d)\.")
_GROUP_LINE = re.compile(
    r"Група (\d\.\d)\. (?:Електроенергія є|Електроенергії немає (з \d\d:\d\d до \d\d:\d\d"
    r"(?:, з \d\d:\d\d до \d\d:\d\d)*))\."
)
_INTERVAL = re.compile(r"з (\d\d):(\d\d) до (\d\d):(\d\d)")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoeSchedule:
    day: date
    published_at: datetime
    groups: dict[str, str]  # group -> 48 slot codes from 00:00


def parse_schedule(raw_html: str) -> LoeSchedule | None:
    """None for an empty item (tomorrow not published yet)."""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", raw_html))
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    day = _search(_DAY, lines, "day")
    published = _search(_PUBLISHED, lines, "publication time")
    groups: dict[str, str] = {}
    for line in lines:
        if not _GROUP.match(line):
            if not (_DAY.search(line) or _PUBLISHED.search(line)):
                logger.warning("loe schedule: unknown line %r", line[:100])
            continue
        match = _GROUP_LINE.fullmatch(line)
        if match is None:
            raise ApiSchemaError(f"loe schedule: unexpected group line {line[:100]!r}")
        group, intervals = match.groups()
        if group in groups or group not in GROUPS:
            raise ApiSchemaError(f"loe schedule: unexpected or repeated group {group}")
        groups[group] = _slots(intervals or "")
    if groups.keys() != GROUPS:
        raise ApiSchemaError(f"loe schedule: groups missing: {sorted(GROUPS - groups.keys())}")
    return LoeSchedule(
        day=datetime.strptime(day.group(1), "%d.%m.%Y").date(),
        published_at=datetime.strptime(
            f"{published.group(2)} {published.group(1)}", "%d.%m.%Y %H:%M"
        ).replace(tzinfo=KYIV),
        groups=groups,
    )


def _search(pattern: re.Pattern[str], lines: list[str], what: str) -> re.Match[str]:
    for line in lines:
        if match := pattern.search(line):
            return match
    raise ApiSchemaError(f"loe schedule: no {what}")


def _slots(intervals: str) -> str:
    codes = [ON] * SLOTS_PER_DAY
    for interval in _INTERVAL.finditer(intervals):
        start_hour, start_minute, end_hour, end_minute = map(int, interval.groups())
        if {start_minute, end_minute} - {0, 30} or end_hour * 60 + end_minute > 24 * 60:
            raise ApiSchemaError(f"loe schedule: bad interval {interval.group(0)!r}")
        start, end = start_hour * 2 + start_minute // 30, end_hour * 2 + end_minute // 30
        if start >= end:
            raise ApiSchemaError(f"loe schedule: empty or reversed interval {interval.group(0)!r}")
        codes[start:end] = [OFF] * (end - start)
    return "".join(codes)

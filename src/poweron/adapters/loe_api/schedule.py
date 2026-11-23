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
_TIME = r"\d\d:[03]0"
_GROUP_LINE = re.compile(
    rf"Група ([1-6]\.[12])\. (?:Електроенергія є|Електроенергії немає (з {_TIME} до {_TIME}"
    rf"(?:, з {_TIME} до {_TIME})*))\."
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
    day = published = None
    groups: dict[str, str] = {}
    for line in lines:
        if match := _DAY.search(line):
            day = datetime.strptime(match.group(1), "%d.%m.%Y").date()
        elif match := _PUBLISHED.search(line):
            published = datetime.strptime(
                f"{match.group(2)} {match.group(1)}", "%d.%m.%Y %H:%M"
            ).replace(tzinfo=KYIV)
        elif line.startswith("Група "):
            match = _GROUP_LINE.fullmatch(line)
            if match is None:
                raise ApiSchemaError(f"loe schedule: unexpected group line {line[:100]!r}")
            group, intervals = match.groups()
            if group in groups:
                raise ApiSchemaError(f"loe schedule: group {group} twice")
            groups[group] = _slots(intervals or "")
        else:
            logger.warning("loe schedule: unknown line %r", line[:100])
    if day is None or published is None:
        raise ApiSchemaError("loe schedule: no day or publication time")
    if groups.keys() != GROUPS:
        raise ApiSchemaError(f"loe schedule: groups missing: {sorted(GROUPS - groups.keys())}")
    return LoeSchedule(day=day, published_at=published, groups=groups)


def _slots(intervals: str) -> str:
    codes = [ON] * SLOTS_PER_DAY
    for interval in _INTERVAL.finditer(intervals):
        start_hour, start_minute, end_hour, end_minute = map(int, interval.groups())
        start, end = start_hour * 2 + start_minute // 30, end_hour * 2 + end_minute // 30
        if not 0 <= start < end <= SLOTS_PER_DAY:
            raise ApiSchemaError(f"loe schedule: bad interval {interval.group(0)!r}")
        codes[start:end] = [OFF] * (end - start)
    return "".join(codes)

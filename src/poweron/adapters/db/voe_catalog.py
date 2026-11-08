"""Volynoblenergo's address catalogue, served from the weekly imported `voe_buildings` table."""

import gzip
import io
import json
import re
import sys
import zlib
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from poweron.adapters.db.tables import catalog_cache, voe_buildings
from poweron.core.domain.models import Building, City, Street
from poweron.core.domain.providers import VOE, VOE_CATALOG_IMPORTED_KEY, scoped_subqueue

SUBQUEUE = re.compile(r"^[1-6]\.[12]$")
MAX_NAME_LENGTHS = (64, 128, 128, 64)  # district, settlement, street, building
MAX_EXPORT_BYTES = 200_000_000
MIN_KEPT_SHARE = 0.8
IMPORT_CHUNK = 5000


class CatalogImportRefused(Exception):
    """The export looks broken; the stored catalogue is kept."""


@dataclass(frozen=True, slots=True)
class CatalogRow:
    district: str
    settlement: str
    street: str
    building: str
    subqueue: str | None  # plain "6.1"; None = «Не залучено»


@dataclass(frozen=True)
class ImportSummary:
    buildings: int
    previous_buildings: int
    changed: int  # buildings whose queues differ from the previous import, new ones included


def parse_export(compressed: bytes) -> list[CatalogRow]:
    """Validate a `scripts/export_volyn_queues.py` file; raise CatalogImportRefused if malformed."""
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as unpacked:
            raw = unpacked.read(MAX_EXPORT_BYTES + 1)  # bounded: never inflate a gzip bomb
        if len(raw) > MAX_EXPORT_BYTES:
            raise CatalogImportRefused("export is too large")
        # One JSON array per line, parsed line by line: the whole document never sits in memory.
        rows = [_row(json.loads(line)) for line in raw.decode().splitlines() if line]
    except (OSError, EOFError, ValueError) as error:
        raise CatalogImportRefused(f"not an export file: {error}") from error
    if not rows:
        raise CatalogImportRefused("the export is empty")
    return rows


def _row(item: Any) -> CatalogRow:
    if not (isinstance(item, list) and len(item) == 5):
        raise CatalogImportRefused(f"bad row: {item!r}")
    district, settlement, street, building, subqueue = item
    names = (district, settlement, street, building)
    for name, max_length in zip(names, MAX_NAME_LENGTHS, strict=True):
        if not (isinstance(name, str) and 0 < len(name) <= max_length):
            raise CatalogImportRefused(f"bad name in row: {item!r}")
    if subqueue is not None and not (isinstance(subqueue, str) and SUBQUEUE.match(subqueue)):
        raise CatalogImportRefused(f"bad subqueue in row: {item!r}")
    # The same district, settlement and street names repeat in thousands of rows.
    return CatalogRow(
        sys.intern(district), sys.intern(settlement), sys.intern(street), building, subqueue
    )


def stable_id(*names: str) -> int:
    """The same names give the same id in every import; fits a signed 32-bit column."""
    return zlib.crc32("|".join(names).encode()) & 0x7FFFFFFF


class VoeCatalog:
    """`CatalogSource` for Volyn; subqueues are namespaced ("voe:6.1")."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def cities(self) -> list[City]:
        query = select(
            voe_buildings.c.settlement_id, voe_buildings.c.settlement, voe_buildings.c.district
        ).distinct()
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [City(id=row[0], name=row[1], otg_name=f"{row[2]} р-н") for row in rows]

    async def streets(self, city_id: int) -> list[Street]:
        query = (
            select(voe_buildings.c.street_id, voe_buildings.c.street)
            .where(voe_buildings.c.settlement_id == city_id)
            .distinct()
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        return [Street(id=row[0], name=row[1]) for row in rows]

    async def buildings(self, city_id: int, street_id: int) -> list[Building]:
        queues = await self._queues(city_id, street_id)
        return [
            Building(id=building_id, name=name, cherg_gpv=subqueues[0] if subqueues else None)
            for (building_id, name), subqueues in queues.items()
        ]

    async def building_subqueues(
        self, city_id: int, street_id: int, building_name: str
    ) -> list[str]:
        queues = await self._queues(city_id, street_id, voe_buildings.c.building == building_name)
        return next(iter(queues.values()), [])

    async def _queues(
        self, city_id: int, street_id: int, *conditions: ColumnElement[bool]
    ) -> dict[tuple[int, str], list[str]]:
        query = select(
            voe_buildings.c.building_id, voe_buildings.c.building, voe_buildings.c.cherg_gpv
        ).where(
            voe_buildings.c.settlement_id == city_id,
            voe_buildings.c.street_id == street_id,
            *conditions,
        )
        async with self._engine.connect() as connection:
            rows = (await connection.execute(query)).all()
        queues: dict[tuple[int, str], set[str]] = defaultdict(set)
        for building_id, name, subqueue in rows:
            found = queues[(building_id, name)]
            if subqueue is not None:
                found.add(scoped_subqueue(VOE, subqueue))
        return {key: sorted(found) for key, found in queues.items()}

    async def replace(
        self, rows: list[CatalogRow], now: datetime, force: bool = False
    ) -> ImportSummary:
        """Swap the whole catalogue in one transaction.

        Refused when it would drop below MIN_KEPT_SHARE of the stored buildings (a broken
        export), unless `force`.
        """
        new = _queues_by_building((_building_id(row), row.subqueue) for row in rows)
        async with self._engine.begin() as connection:
            stored = await connection.execute(
                select(voe_buildings.c.building_id, voe_buildings.c.cherg_gpv)
            )
            previous = _queues_by_building((row[0], row[1]) for row in stored)
            if not force and len(new) < MIN_KEPT_SHARE * len(previous):
                raise CatalogImportRefused(
                    f"{len(new)} buildings instead of {len(previous)}; use --force if real"
                )
            await connection.execute(delete(voe_buildings))
            for start in range(0, len(rows), IMPORT_CHUNK):  # chunks keep the peak memory low
                chunk = [_values(row) for row in rows[start : start + IMPORT_CHUNK]]
                await connection.execute(voe_buildings.insert(), chunk)
            # Written here rather than through the repository, so the marker and the
            # catalogue change in the same transaction.
            await connection.execute(
                delete(catalog_cache).where(catalog_cache.c.key == VOE_CATALOG_IMPORTED_KEY)
            )
            await connection.execute(
                catalog_cache.insert().values(
                    key=VOE_CATALOG_IMPORTED_KEY, value={"buildings": len(new)}, fetched_at=now
                )
            )
        changed = sum(1 for key, found in new.items() if previous.get(key) != found)
        return ImportSummary(len(new), len(previous), changed)


def _values(row: CatalogRow) -> dict[str, Any]:
    return {
        "settlement_id": stable_id(row.district, row.settlement),
        "district": row.district,
        "settlement": row.settlement,
        "street_id": stable_id(row.district, row.settlement, row.street),
        "street": row.street,
        "building_id": _building_id(row),
        "building": row.building,
        "cherg_gpv": row.subqueue,
    }


def _building_id(row: CatalogRow) -> int:
    return stable_id(row.district, row.settlement, row.street, row.building)


def _queues_by_building(pairs: Iterable[tuple[int, str | None]]) -> dict[int, str]:
    """Building id → its sorted queues as one string; strings are much smaller than sets."""
    queues: dict[int, set[str]] = defaultdict(set)
    for building_id, subqueue in pairs:
        queues[building_id].add(subqueue or "")
    return {building_id: ",".join(sorted(found)) for building_id, found in queues.items()}

"""Volyn outages going on now, imported every 15 minutes from the owner's Mac.

The Mac runs `scripts/export_volyn_outages.py` (the server is challenged by Cloudflare on
energy.volyn.ua) and pipes its JSON into `python -m poweron.import_voe_outages`.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError
from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncEngine

from poweron.adapters.db.tables import catalog_cache, voe_outages
from poweron.adapters.db.voe_catalog import stable_id
from poweron.core.domain.models import KYIV, OutageKind, PlannedWork

# Not under "voe:": the weekly catalogue import clears every key with that prefix.
SNAPSHOT_KEY = "voe_outages:snapshot"
# The Mac sends a snapshot every 15 minutes; one this old means it is asleep or offline.
MAX_AGE = timedelta(hours=1)
MAX_SNAPSHOT_BYTES = 5_000_000

Name = Annotated[str, StringConstraints(min_length=1, max_length=128)]
BuildingName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
WallClock = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d\d-\d\d \d\d:\d\d$")]
Reason = Annotated[str, StringConstraints(max_length=256)]
Row = tuple[
    Name,  # district
    Name,  # settlement
    Name,  # street
    Annotated[list[BuildingName], Field(min_length=1, max_length=1000)],
    Literal["emergency", "planned"],
    WallClock,  # start
    WallClock,  # expected end
    Reason,
]


class OutagesImportRefused(Exception):
    """The snapshot is not in the export format; the stored one is kept."""


ROW_ADAPTER: TypeAdapter[Row] = TypeAdapter(Row)


class _Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[Any]  # validated one by one, so one odd row does not drop the rest


@dataclass(frozen=True)
class OutageRow:
    settlement_id: int
    street_id: int
    kind: OutageKind
    starts_at: datetime
    ends_at: datetime
    reason: str
    building_names: tuple[str, ...]


def parse_snapshot(raw: bytes) -> tuple[list[OutageRow], int]:
    """Rows of a snapshot and how many were skipped as invalid.

    A file that is not a snapshot, or one where every row is invalid (the export format
    changed), is refused; an empty snapshot is fine: no outages anywhere.
    """
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise OutagesImportRefused("snapshot is too large")
    try:
        items = _Snapshot.model_validate_json(raw).rows
    except ValidationError as error:
        raise OutagesImportRefused(f"not an outages snapshot: {error}") from error
    rows: list[OutageRow] = []
    for item in items:
        try:
            rows.append(_row(*ROW_ADAPTER.validate_python(item)))
        except (ValidationError, ValueError):
            continue
    if items and not rows:
        raise OutagesImportRefused(f"all {len(items)} rows are invalid")
    return rows, len(items) - len(rows)


def _row(
    district: str,
    settlement: str,
    street: str,
    buildings: list[str],
    kind: str,
    starts: str,
    ends: str,
    reason: str,
) -> OutageRow:
    return OutageRow(
        settlement_id=stable_id(district, settlement),
        street_id=stable_id(district, settlement, street),
        kind=OutageKind(kind),
        starts_at=_from_kyiv(starts),
        ends_at=_from_kyiv(ends),
        reason=reason,
        building_names=tuple(buildings),
    )


def _from_kyiv(wall_clock: str) -> datetime:
    return datetime.strptime(wall_clock, "%Y-%m-%d %H:%M").replace(tzinfo=KYIV).astimezone(UTC)


class VoeOutages:
    """`CurrentOutageSource` for Volyn: the last snapshot, ignored once it is older than MAX_AGE."""

    def __init__(
        self, engine: AsyncEngine, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._engine = engine
        self._clock = clock

    async def emergency_outages(self, city_id: int, street_id: int) -> list[PlannedWork]:
        return await self._works(OutageKind.EMERGENCY, city_id, street_id)

    async def planned_works(
        self, city_id: int, street_id: int, after: datetime
    ) -> list[PlannedWork]:
        """Only works already going on: the site lists nothing ahead."""
        return await self._works(
            OutageKind.PLANNED, city_id, street_id, voe_outages.c.ends_at > after
        )

    async def _works(
        self, kind: OutageKind, city_id: int, street_id: int, *conditions: ColumnElement[bool]
    ) -> list[PlannedWork]:
        async with self._engine.connect() as connection:
            fetched_at = await connection.scalar(
                select(catalog_cache.c.fetched_at).where(catalog_cache.c.key == SNAPSHOT_KEY)
            )
            if fetched_at is None or fetched_at < self._clock() - MAX_AGE:
                return []
            rows = await connection.execute(
                select(voe_outages).where(
                    voe_outages.c.settlement_id == city_id,
                    voe_outages.c.street_id == street_id,
                    voe_outages.c.kind == kind.value,
                    *conditions,
                )
            )
            return [
                PlannedWork(
                    id=row.id,
                    street_id=row.street_id,
                    starts_at=row.starts_at,
                    ends_at=row.ends_at,
                    reason=row.reason,
                    building_names=tuple(row.building_names),
                )
                for row in rows
            ]

    async def replace(self, rows: list[OutageRow], now: datetime) -> None:
        """Swap the whole snapshot and its time in one transaction."""
        async with self._engine.begin() as connection:
            await connection.execute(delete(voe_outages))
            if rows:
                await connection.execute(voe_outages.insert(), [_values(row) for row in rows])
            await connection.execute(
                delete(catalog_cache).where(catalog_cache.c.key == SNAPSHOT_KEY)
            )
            await connection.execute(
                catalog_cache.insert().values(
                    key=SNAPSHOT_KEY, value={"rows": len(rows)}, fetched_at=now
                )
            )


def _values(row: OutageRow) -> dict[str, Any]:
    return {
        "settlement_id": row.settlement_id,
        "street_id": row.street_id,
        "kind": row.kind.value,
        "starts_at": row.starts_at,
        "ends_at": row.ends_at,
        "reason": row.reason,
        "building_names": list(row.building_names),
    }

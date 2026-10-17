from typing import Annotated, Any

from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    TypeAdapter,
    field_validator,
)

SlotKey = Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[03]0$")]
NO_SCHEDULE = {"", "Не входить"}


def subqueue(raw: str | None) -> str | None:
    """Trimmed subqueue id with any `#suffix` kept (the site keys dataJson by it), or None."""
    value = (raw or "").strip()
    return None if value in NO_SCHEDULE else value


class GpvGroup(BaseModel):
    times: dict[SlotKey, str]


class GpvGraph(BaseModel):
    dateCreate: AwareDatetime
    dateGraph: AwareDatetime
    dataJson: dict[str, GpvGroup]

    @field_validator("dataJson", mode="before")
    @classmethod
    def php_empty_map(cls, value: Any) -> Any:
        return {} if value == [] else value


class GpvCollection(BaseModel):
    member: list[GpvGraph] | None = Field(alias="hydra:member")


class Otg(BaseModel):
    name: str


class RawCity(BaseModel):
    id: int
    name: str
    otg: Otg | None = None


class RawStreet(BaseModel):
    id: int
    name: str


class RawBuilding(BaseModel):
    id: int
    buildingName: str
    chergGpv: str | None = None

    @field_validator("chergGpv")
    @classmethod
    def to_subqueue(cls, value: str | None) -> str | None:
        return subqueue(value)


class BuildingNames(BaseModel):
    buildingNames: list[RawBuilding]


class BuildingGroup(BaseModel):
    chergGpv: str | None = None


class BuildingGroups(BaseModel):
    buildingGroups: list[BuildingGroup]


SCHEDULES_ADAPTER = TypeAdapter(GpvCollection)
CITIES_ADAPTER = TypeAdapter(list[RawCity])
STREETS_ADAPTER = TypeAdapter(list[RawStreet])
BUILDINGS_ADAPTER = TypeAdapter(BuildingNames)
BUILDING_GROUPS_ADAPTER = TypeAdapter(BuildingGroups)

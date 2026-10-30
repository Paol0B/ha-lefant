from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import LefantConfigEntry, LefantCoordinator
from .entity import LefantEntity

PARALLEL_UPDATES = 0

ERROR_OPTIONS = ["none", *protocol.FAULTS, "other"]


def _error(data: dict[str, Any]) -> str:
    faults = protocol.active_faults(data.get(protocol.DP_FAULT))
    if not faults:
        return "none"
    return faults[0] if faults[0] in protocol.FAULTS else "other"


@dataclass(frozen=True, kw_only=True)
class LefantSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, kw_only=True)
class LefantUsageSensorDescription(SensorEntityDescription):
    part: str


@dataclass(frozen=True, kw_only=True)
class LefantCleaningSensorDescription(SensorEntityDescription):
    value_fn: Callable[[LefantCoordinator], datetime | int | None]


SENSORS = (
    LefantSensorDescription(
        key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: d.get(protocol.DP_BATTERY),
    ),
    LefantSensorDescription(
        key="cleaning_time",
        translation_key="cleaning_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda d: d.get(protocol.DP_CLEAN_TIME),
    ),
    LefantSensorDescription(
        key="cleaning_area",
        translation_key="cleaning_area",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        value_fn=lambda d: d.get(protocol.DP_CLEAN_AREA),
    ),
    LefantSensorDescription(
        key="status",
        translation_key="status",
        device_class=SensorDeviceClass.ENUM,
        options=protocol.STATUSES,
        value_fn=lambda d: d.get(protocol.DP_STATUS) if d.get(protocol.DP_STATUS) in protocol.STATUSES else None,
    ),
    LefantSensorDescription(
        key="error",
        translation_key="error",
        device_class=SensorDeviceClass.ENUM,
        options=ERROR_OPTIONS,
        value_fn=_error,
    ),
    LefantSensorDescription(
        key="alarm_code",
        translation_key="alarm_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d: d.get(protocol.DP_ALARM_CODE),
    ),
)

USAGE_SENSORS = (
    *(
        LefantUsageSensorDescription(
            key=f"{part}_usage",
            translation_key=f"{part}_usage",
            part=part,
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_unit_of_measurement=UnitOfTime.HOURS,
            suggested_display_precision=1,
        )
        for part in protocol.WEAR_PARTS
    ),
    LefantUsageSensorDescription(
        key="dust_bag_emptyings",
        translation_key="dust_bag_emptyings",
        part="dust_bag",
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
)

CLEANING_SENSORS = (
    LefantCleaningSensorDescription(
        key="last_cleaning_end",
        translation_key="last_cleaning_end",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda c: c.last_cleaning.end if c.last_cleaning else None,
    ),
    LefantCleaningSensorDescription(
        key="last_cleaning_duration",
        translation_key="last_cleaning_duration",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        value_fn=lambda c: c.last_cleaning.minutes if c.last_cleaning else None,
    ),
    LefantCleaningSensorDescription(
        key="last_cleaning_area",
        translation_key="last_cleaning_area",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_METERS,
        value_fn=lambda c: c.last_cleaning.area if c.last_cleaning else None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [LefantSensor(coordinator, d) for d in SENSORS]
    entities.extend(LefantUsageSensor(coordinator, d) for d in USAGE_SENSORS)
    if coordinator.cloud:
        entities.extend(LefantCleaningSensor(coordinator, d) for d in CLEANING_SENSORS)
    async_add_entities(entities)


class LefantSensor(LefantEntity, SensorEntity):
    entity_description: LefantSensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})


class LefantUsageSensor(LefantEntity, SensorEntity):
    entity_description: LefantUsageSensorDescription

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> int:
        return self.coordinator.usage[self.entity_description.part]


class LefantCleaningSensor(LefantEntity, SensorEntity):
    entity_description: LefantCleaningSensorDescription

    @property
    def available(self) -> bool:
        return self.coordinator.last_cleaning is not None

    @property
    def native_value(self) -> datetime | int | None:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.key != "last_cleaning_end" or not self.coordinator.last_cleaning:
            return None
        names = self.coordinator.room_names()
        return {"rooms": [names.get(r, f"Room {r}") for r in self.coordinator.last_cleaning.rooms]}

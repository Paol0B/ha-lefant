from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import LefantConfigEntry
from .entity import LefantEntity

PARALLEL_UPDATES = 0

BINARY_SENSORS = (
    BinarySensorEntityDescription(key=protocol.DP_MOP_ATTACHED, translation_key="mop_attached"),
    BinarySensorEntityDescription(key=protocol.DP_ON_DOCK, translation_key="docked"),
    BinarySensorEntityDescription(
        key=protocol.DP_FAULT, translation_key="problem", device_class=BinarySensorDeviceClass.PROBLEM
    ),
)

BASE_SENSORS = tuple(
    BinarySensorEntityDescription(
        key=f"base_{flag}", translation_key=f"base_{flag}", device_class=BinarySensorDeviceClass.PROBLEM
    )
    for flag in protocol.BASE_FLAGS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            *(LefantBinarySensor(coordinator, d) for d in BINARY_SENSORS),
            *(LefantBaseSensor(coordinator, d) for d in BASE_SENSORS),
        ]
    )


class LefantBinarySensor(LefantEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        value = self.dp(self.entity_description.key)
        # the robot reports DP 114 only when a fault appears
        if self.entity_description.key == protocol.DP_FAULT:
            return bool(value)
        return None if value is None else bool(value)


class LefantBaseSensor(LefantEntity, BinarySensorEntity):
    @property
    def is_on(self) -> bool | None:
        flags = protocol.parse_base_state(self.dp(protocol.DP_BASE_STATE))
        if flags is None:
            return None
        return bool(flags[protocol.BASE_FLAGS[self.entity_description.key.removeprefix("base_")]])

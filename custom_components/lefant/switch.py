from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import LefantConfigEntry
from .entity import LefantEntity

PARALLEL_UPDATES = 0

SWITCHES = (
    SwitchEntityDescription(
        key=protocol.DP_CARPET_BOOST, translation_key="carpet_boost", entity_category=EntityCategory.CONFIG
    ),
    SwitchEntityDescription(
        key=protocol.DP_CARPET_DETECTION, translation_key="carpet_detection", entity_category=EntityCategory.CONFIG
    ),
    SwitchEntityDescription(
        key=protocol.DP_RESUME, translation_key="resume_after_charge", entity_category=EntityCategory.CONFIG
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LefantSwitch(entry.runtime_data, d) for d in SWITCHES)


class LefantSwitch(LefantEntity, SwitchEntity):
    @property
    def is_on(self) -> bool | None:
        value = self.dp(self.entity_description.key)
        return None if value is None else bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_command({self.entity_description.key: True})

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_command({self.entity_description.key: False})

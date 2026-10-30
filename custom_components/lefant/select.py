from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import LefantConfigEntry
from .entity import LefantEntity

PARALLEL_UPDATES = 0

SELECTS = (
    SelectEntityDescription(key=protocol.DP_WATER, translation_key="water_level", options=protocol.WATER_LEVELS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LefantSelect(entry.runtime_data, d) for d in SELECTS)


class LefantSelect(LefantEntity, SelectEntity):
    @property
    def current_option(self) -> str | None:
        value = self.dp(self.entity_description.key)
        return value if value in self.options else None

    async def async_select_option(self, option: str) -> None:
        await self._async_command({self.entity_description.key: option})

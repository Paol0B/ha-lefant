from typing import Any

from homeassistant.components.image import ImageEntity, ImageEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import LefantConfigEntry, LefantCoordinator
from .entity import LefantEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    if coordinator.cloud:
        async_add_entities([LefantMap(hass, coordinator)])


class LefantMap(LefantEntity, ImageEntity):
    _attr_content_type = "image/png"
    _attr_translation_key = "map"

    def __init__(self, hass: HomeAssistant, coordinator: LefantCoordinator) -> None:
        LefantEntity.__init__(self, coordinator, ImageEntityDescription(key="map"))
        ImageEntity.__init__(self, hass)
        self._attr_image_last_updated = coordinator.map_updated

    @property
    def available(self) -> bool:
        return self.coordinator.map_image is not None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"rooms": {str(k): v for k, v in self.coordinator.room_names().items()}}

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_image_last_updated = self.coordinator.map_updated
        super()._handle_coordinator_update()

    async def async_image(self) -> bytes | None:
        return self.coordinator.map_image

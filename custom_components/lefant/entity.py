from typing import Any

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import protocol
from .const import DOMAIN, MANUFACTURER
from .coordinator import LefantCoordinator
from .device import LefantDeviceError


class LefantEntity(CoordinatorEntity[LefantCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: LefantCoordinator, description: EntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.device_id}_{description.key}"
        mac = protocol.parse_mac((coordinator.data or {}).get(protocol.DP_MAC))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_id)},
            connections={(CONNECTION_NETWORK_MAC, mac)} if mac else set(),
            manufacturer=MANUFACTURER,
            name=coordinator.config_entry.title,
            model=coordinator.config_entry.title.removeprefix(f"{MANUFACTURER} "),
        )

    @property
    def available(self) -> bool:
        return self.coordinator.connected

    def dp(self, key: str) -> Any:
        return (self.coordinator.data or {}).get(key)

    async def _async_command(self, dps: dict[str, Any]) -> None:
        try:
            await self.coordinator.async_command(dps)
        except (LefantDeviceError, TimeoutError) as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_failed",
                translation_placeholders={"entity_id": self.entity_id, "error": str(err) or "timeout"},
            ) from err

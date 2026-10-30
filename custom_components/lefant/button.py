from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .coordinator import LefantConfigEntry
from .entity import LefantEntity

PARALLEL_UPDATES = 0

RESET_BUTTONS = tuple(
    ButtonEntityDescription(key=f"reset_{part}", translation_key=f"reset_{part}", entity_category=EntityCategory.CONFIG)
    for part in (*protocol.WEAR_PARTS, "dust_bag")
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities(LefantResetButton(entry.runtime_data, d) for d in RESET_BUTTONS)


class LefantResetButton(LefantEntity, ButtonEntity):
    """Marks a part as replaced: its usage counter starts again from 0."""

    @property
    def available(self) -> bool:
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_reset_usage(self.entity_description.key.removeprefix("reset_"))

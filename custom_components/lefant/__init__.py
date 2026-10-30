import asyncio
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .cloud import TuyaCloud
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_REGION,
    CONNECT_TIMEOUT,
    DEFAULT_REGION,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import LefantConfigEntry, LefantCoordinator
from .device import LefantDevice
from .websocket import async_setup_websocket

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_FILE = Path(__file__).parent / "frontend" / "lefant-vacuum-card.js"
CARD_URL = f"/{DOMAIN}_static/lefant-vacuum-card.js"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_websocket(hass)
    # served for a Lovelace resource: as an extra frontend module the card would load
    # before the scoped element registry and the dashboard could not find it
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_FILE), True)])
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LefantConfigEntry) -> bool:
    data = entry.data
    cloud = None
    if data.get(CONF_ACCESS_ID) and data.get(CONF_ACCESS_SECRET):
        cloud = TuyaCloud(
            async_get_clientsession(hass),
            data.get(CONF_REGION, DEFAULT_REGION),
            data[CONF_ACCESS_ID],
            data[CONF_ACCESS_SECRET],
        )
    coordinator = LefantCoordinator(hass, entry, cloud)
    await coordinator.async_load_usage()
    device = LefantDevice(
        hass.loop,
        data[CONF_DEVICE_ID],
        data[CONF_HOST],
        data[CONF_LOCAL_KEY],
        data[CONF_PROTOCOL_VERSION],
        coordinator.async_handle_dps,
        coordinator.async_handle_connection,
    )
    coordinator.device = device

    async def _stop_device() -> None:
        await hass.async_add_executor_job(device.stop)

    device.start()
    # also runs when setup fails below
    entry.async_on_unload(_stop_device)
    try:
        await asyncio.wait_for(coordinator.connected_event.wait(), CONNECT_TIMEOUT)
    except TimeoutError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": data[CONF_HOST], "error": str(device.last_error)},
        ) from err

    await coordinator.async_load_cloud_state()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_map_updates()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: LefantConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

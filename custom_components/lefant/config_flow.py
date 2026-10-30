import logging
from typing import Any

import tinytuya
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlowWithReload
from homeassistant.const import CONF_HOST
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud import TuyaCloud, TuyaCloudError
from .const import (
    CONF_ACCESS_ID,
    CONF_ACCESS_SECRET,
    CONF_DEVICE_ID,
    CONF_LOCAL_KEY,
    CONF_PROTOCOL_VERSION,
    CONF_REGION,
    CONF_ROOM_NAMES,
    DEFAULT_PROTOCOL_VERSION,
    DEFAULT_REGION,
    DOMAIN,
    MANUFACTURER,
    PROTOCOL_VERSIONS,
    REGIONS,
)
from .coordinator import LefantConfigEntry

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_DEVICE_ID): str,
        vol.Required(CONF_LOCAL_KEY): str,
        vol.Required(CONF_PROTOCOL_VERSION, default=DEFAULT_PROTOCOL_VERSION): selector.SelectSelector(
            selector.SelectSelectorConfig(options=PROTOCOL_VERSIONS)
        ),
        vol.Optional(CONF_ACCESS_ID): str,
        vol.Optional(CONF_ACCESS_SECRET): str,
        vol.Required(CONF_REGION, default=DEFAULT_REGION): selector.SelectSelector(
            selector.SelectSelectorConfig(options=list(REGIONS))
        ),
    }
)


def _local_status(user_input: dict[str, Any]) -> dict[str, Any]:
    dev = tinytuya.Device(
        user_input[CONF_DEVICE_ID],
        user_input[CONF_HOST],
        user_input[CONF_LOCAL_KEY],
        version=float(user_input[CONF_PROTOCOL_VERSION]),
        connection_timeout=5,
    )
    try:
        return dev.status() or {}
    finally:
        dev.close()


class LefantConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry: LefantConfigEntry) -> "LefantOptionsFlow":
        return LefantOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_DEVICE_ID])
            self._abort_if_unique_id_configured(updates={CONF_HOST: user_input[CONF_HOST]})
            title = MANUFACTURER
            status = await self.hass.async_add_executor_job(_local_status, user_input)
            if "dps" not in status:
                _LOGGER.debug("Local connection failed: %s", status)
                errors["base"] = "cannot_connect"
            elif user_input.get(CONF_ACCESS_ID) or user_input.get(CONF_ACCESS_SECRET):
                cloud = TuyaCloud(
                    async_get_clientsession(self.hass),
                    user_input[CONF_REGION],
                    user_input.get(CONF_ACCESS_ID, ""),
                    user_input.get(CONF_ACCESS_SECRET, ""),
                )
                try:
                    info = await cloud.device(user_input[CONF_DEVICE_ID])
                except TuyaCloudError as err:
                    _LOGGER.debug("Cloud check failed: %s", err)
                    errors["base"] = "cloud_failed"
                else:
                    title = info.get("product_name") or info.get("name") or title
            if not errors:
                return self.async_create_entry(title=title, data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )


class LefantOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        coordinator = self.config_entry.runtime_data
        if user_input is not None:
            names = {key.removeprefix("room_"): value.strip() for key, value in user_input.items() if value.strip()}
            return self.async_create_entry(data={CONF_ROOM_NAMES: names})
        current = self.config_entry.options.get(CONF_ROOM_NAMES, {})
        schema = vol.Schema(
            {
                vol.Optional(
                    f"room_{room_id}",
                    description={"suggested_value": current.get(str(room_id)) or name},
                ): str
                for room_id, name in sorted(coordinator.robot_rooms.items())
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={"rooms": ", ".join(map(str, sorted(coordinator.robot_rooms)))},
        )

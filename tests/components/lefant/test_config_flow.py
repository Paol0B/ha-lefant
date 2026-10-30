from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lefant.cloud import TuyaCloudError
from custom_components.lefant.const import DOMAIN

from . import CLOUD_DATA, DEVICE_ID, ENTRY_DATA

LOCAL_OK = {"dps": {"1": False}}


@pytest.fixture(autouse=True)
def no_setup() -> Any:
    with patch("custom_components.lefant.async_setup_entry", return_value=True):
        yield


async def _submit(hass: HomeAssistant, data: dict[str, Any], status: dict[str, Any]) -> Any:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch("custom_components.lefant.config_flow._local_status", return_value=status):
        return await hass.config_entries.flow.async_configure(result["flow_id"], data)


async def test_local_only(hass: HomeAssistant) -> None:
    result = await _submit(hass, ENTRY_DATA, LOCAL_OK)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Lefant"
    assert result["data"] == ENTRY_DATA
    assert result["result"].unique_id == DEVICE_ID


async def test_cannot_connect(hass: HomeAssistant) -> None:
    result = await _submit(hass, ENTRY_DATA, {"Error": "Network Error: Device Unreachable", "Err": "905"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_cloud(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.lefant.config_flow.TuyaCloud.device",
        new=AsyncMock(return_value={"product_name": "Lefant M5 Max"}),
    ):
        result = await _submit(hass, CLOUD_DATA, LOCAL_OK)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Lefant M5 Max"


async def test_cloud_failed(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.lefant.config_flow.TuyaCloud.device",
        new=AsyncMock(side_effect=TuyaCloudError("1106 permission deny")),
    ):
        result = await _submit(hass, CLOUD_DATA, LOCAL_OK)
    assert result["errors"] == {"base": "cloud_failed"}


async def test_already_configured_updates_host(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=DEVICE_ID)
    entry.add_to_hass(hass)
    result = await _submit(hass, {**ENTRY_DATA, "host": "192.0.2.20"}, LOCAL_OK)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.0.2.20"

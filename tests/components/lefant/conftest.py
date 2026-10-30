from collections.abc import Generator
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.lefant.const import DOMAIN

from . import DEVICE_ID, ENTRY_DATA, FakeDevice


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    return


@pytest.fixture
def fake_device() -> Generator[list[FakeDevice]]:
    devices: list[FakeDevice] = []

    def create(*args: object) -> FakeDevice:
        devices.append(FakeDevice(*args))  # type: ignore[arg-type]
        return devices[-1]

    with patch("custom_components.lefant.LefantDevice", side_effect=create):
        yield devices


@pytest.fixture
async def entry(hass: HomeAssistant, fake_device: list[FakeDevice]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=DEVICE_ID, title="Lefant M5 Max")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry

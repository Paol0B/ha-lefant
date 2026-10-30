from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator, WebSocketGenerator

from custom_components.lefant import protocol
from custom_components.lefant.cloud import TuyaCloudError
from custom_components.lefant.const import DOMAIN, MAP_REFRESH_DELAYS

from . import CLOUD_DATA, DEVICE_ID, FakeDevice, rooms_dp
from .test_protocol import record_file

VACUUM = "vacuum.lefant_m5_max"
MAP_IMAGE = "image.lefant_m5_max_last_cleaning_map"
RECORD, SECTIONS = record_file(route=[(0, 0), (10, -10)], rooms=[1, 2])
AREAS_REPORT = protocol.encode(bytes([protocol.CMD_AREAS_REPORT, 1, 1, 3]) + b"\x00\x00\x00\x00\x00\x0a\x00\x00\x00\x0a\xff\xf6")


def record(record_id: int) -> dict[str, Any]:
    return {"id": record_id, "time": "1767225600", "extend": "0_0_0_42_31_" + "_".join(map(str, SECTIONS))}


@pytest.fixture
def cloud() -> Generator[dict[str, AsyncMock]]:
    mocks = {
        "shadow": AsyncMock(return_value={protocol.DP_AREAS: AREAS_REPORT}),
        "latest_record": AsyncMock(return_value=record(7)),
        "record_map": AsyncMock(return_value=RECORD),
    }
    with patch.multiple("custom_components.lefant.cloud.TuyaCloud", **mocks):
        yield mocks


@pytest.fixture
async def entry(hass: HomeAssistant, fake_device: list[FakeDevice], cloud: dict[str, AsyncMock]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data=CLOUD_DATA, unique_id=DEVICE_ID, title="Lefant M5 Max")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def _ws(hass: HomeAssistant, hass_ws_client: WebSocketGenerator, **msg: Any) -> dict[str, Any]:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"entity_id": VACUUM, **msg})
    return await client.receive_json()


async def test_map_from_cloud(
    hass: HomeAssistant, entry: MockConfigEntry, hass_client: ClientSessionGenerator, hass_ws_client: WebSocketGenerator
) -> None:
    assert hass.states.get(MAP_IMAGE).attributes["rooms"] == {"1": "Kitchen", "2": "Hall"}
    client = await hass_client()
    resp = await client.get(f"/api/image_proxy/{MAP_IMAGE}")
    assert resp.status == 200
    assert (await resp.read()).startswith(b"\x89PNG")

    last = hass.states.get("sensor.lefant_m5_max_last_cleaning")
    assert last.state == "2026-01-01T00:00:00+00:00"
    assert last.attributes["rooms"] == ["Kitchen", "Hall"]
    assert hass.states.get("sensor.lefant_m5_max_last_cleaning_duration").state == "42"

    result = (await _ws(hass, hass_ws_client, type="lefant/map"))["result"]
    assert result["editable"]
    assert [r["id"] for r in result["rooms"]] == [1, 2]
    assert result["map"]["route"] == "M3.0 2.0L4.0 3.0"
    assert result["areas"] == [{"mode": 1, "points": [[3.0, 2.0], [4.0, 2.0], [4.0, 3.0]]}]
    assert result["last_cleaning"]["names"] == {"1": "Kitchen", "2": "Hall"}


async def test_set_zones(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], hass_ws_client: WebSocketGenerator
) -> None:
    device = fake_device[0]
    report = protocol.encode(bytes([protocol.CMD_AREAS_REPORT, 1, protocol.WALL_MODE, 2]) + b"\xff\xec\x00\x0a\x00\x00\x00\x0a")
    device.responder = lambda dps: [{protocol.DP_AREAS: report}]
    msg = await _ws(hass, hass_ws_client, type="lefant/set_zones", areas=[], walls=[[[1, 1], [3, 1]]])
    assert msg["success"]
    assert device.sent == [{protocol.DP_COMMAND: protocol.zones_command([], [[(-20, 10), (0, 10)]])}]
    assert msg["result"]["walls"] == [[[1.0, 1.0], [3.0, 1.0]]]
    assert msg["result"]["areas"] == []


async def test_set_zones_unconfirmed(
    hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator
) -> None:
    with patch("custom_components.lefant.coordinator.EDIT_TIMEOUT", 0.01):
        msg = await _ws(hass, hass_ws_client, type="lefant/set_zones", areas=[], walls=[])
    assert msg["error"]["message"] == "the robot did not confirm the change"


async def test_split_room(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], hass_ws_client: WebSocketGenerator
) -> None:
    device = fake_device[0]
    device.responder = lambda dps: [
        {protocol.DP_COMMAND: protocol.encode(bytes([protocol.CMD_SPLIT_REPORT, 1]))},
        {protocol.DP_ROOMS: rooms_dp({1: "Kitchen", 2: "Hall", 3: ""})},
    ]
    msg = await _ws(hass, hass_ws_client, type="lefant/split_room", room_id=1, line=[[0.5, 0], [0.5, 4]])
    assert msg["success"]
    assert device.sent == [{protocol.DP_COMMAND: protocol.split_command(1, [(-25, 20), (-25, -20)])}]
    assert msg["result"]["map_edited"]
    assert {r["id"]: r["name"] for r in msg["result"]["rooms"]} == {1: "Kitchen", 2: "Hall", 3: "Room 3"}
    assert "path" in msg["result"]["rooms"][2]

    # the edit preview survives a reload until the robot sends a new record
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.map_edited


async def test_merge_rooms(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], hass_ws_client: WebSocketGenerator
) -> None:
    device = fake_device[0]
    device.responder = lambda dps: [
        {protocol.DP_COMMAND: protocol.encode(bytes([protocol.CMD_MERGE_REPORT, 1]))},
        {protocol.DP_ROOMS: rooms_dp({1: "Kitchen"})},
    ]
    msg = await _ws(hass, hass_ws_client, type="lefant/merge_rooms", room_ids=[1, 2])
    assert msg["success"]
    assert [r["id"] for r in msg["result"]["rooms"]] == [1]
    assert 8 not in entry.runtime_data._cmap.pixels


async def test_edit_refused(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], hass_ws_client: WebSocketGenerator
) -> None:
    fake_device[0].responder = lambda dps: [{protocol.DP_COMMAND: protocol.encode(bytes([protocol.CMD_MERGE_REPORT, 0]))}]
    msg = await _ws(hass, hass_ws_client, type="lefant/merge_rooms", room_ids=[1, 2])
    assert "refused" in msg["error"]["message"]


async def test_no_edit_while_cleaning(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], hass_ws_client: WebSocketGenerator
) -> None:
    fake_device[0].on_dps({protocol.DP_STATUS: "cleaning"})
    msg = await _ws(hass, hass_ws_client, type="lefant/merge_rooms", room_ids=[1, 2])
    assert "not cleaning" in msg["error"]["message"]
    assert fake_device[0].sent == []


async def test_new_record_drops_edits(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], cloud: dict[str, AsyncMock],
    hass_ws_client: WebSocketGenerator,
) -> None:
    device = fake_device[0]
    device.responder = lambda dps: [
        {protocol.DP_COMMAND: protocol.encode(bytes([protocol.CMD_MERGE_REPORT, 1]))},
        {protocol.DP_ROOMS: rooms_dp({1: "Kitchen"})},
    ]
    assert (await _ws(hass, hass_ws_client, type="lefant/merge_rooms", room_ids=[1, 2]))["success"]
    coordinator = entry.runtime_data
    assert coordinator.map_edited

    # docking after a cleaning asks the cloud for the new record
    device.on_dps({protocol.DP_STATUS: "cleaning"})
    device.on_dps({protocol.DP_STATUS: "charging"})
    assert len(coordinator._map_retries) == len(MAP_REFRESH_DELAYS)
    cloud["latest_record"].return_value = record(8)
    await coordinator._async_refresh_map()
    assert not coordinator.map_edited
    # room 2 is gone on the robot, so the old record draws it as plain floor
    assert {r["id"] for r in coordinator.map_geometry["rooms"]} == {1}


async def test_cloud_down(hass: HomeAssistant, fake_device: list[FakeDevice], cloud: dict[str, AsyncMock]) -> None:
    cloud["shadow"].side_effect = TuyaCloudError("down")
    cloud["latest_record"].side_effect = TuyaCloudError("down")
    entry = MockConfigEntry(domain=DOMAIN, data=CLOUD_DATA, unique_id=DEVICE_ID, title="Lefant M5 Max")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get(VACUUM).state == "docked"
    assert hass.states.get(MAP_IMAGE).state == "unavailable"


async def test_bad_record(hass: HomeAssistant, fake_device: list[FakeDevice], cloud: dict[str, AsyncMock]) -> None:
    cloud["latest_record"].return_value = {"id": 9, "time": "1", "extend": "garbage"}
    entry = MockConfigEntry(domain=DOMAIN, data=CLOUD_DATA, unique_id=DEVICE_ID, title="Lefant M5 Max")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.map_image is None
    cloud["record_map"].assert_not_called()

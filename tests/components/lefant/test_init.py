from datetime import timedelta
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import EVENT_HOMEASSISTANT_FINAL_WRITE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.lefant import protocol
from custom_components.lefant.const import DOMAIN
from custom_components.lefant.coordinator import BASE_SETTLE, DOCK_PAUSE

from . import DEVICE_ID, ENTRY_DATA, FakeDevice

VACUUM = "vacuum.lefant_m5_max"


async def test_setup_and_unload(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert entry.state is ConfigEntryState.LOADED
    assert hass.states.get(VACUUM).state == "docked"
    assert hass.states.get("sensor.lefant_m5_max_battery").state == "87"
    assert hass.states.get("sensor.lefant_m5_max_status").state == "charging"
    assert hass.states.get("binary_sensor.lefant_m5_max_dirty_water_tank").state == "on"
    assert hass.states.get("binary_sensor.lefant_m5_max_clean_water_tank").state == "off"
    assert hass.states.get("select.lefant_m5_max_water_level").state == "low"
    assert hass.states.get("switch.lefant_m5_max_carpet_boost").state == "on"
    # the map entity needs the cloud project or a map saved from an earlier run
    assert hass.states.get("image.lefant_m5_max_last_cleaning_map") is None

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retry_when_unreachable(hass: HomeAssistant, fake_device: list[FakeDevice]) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA, unique_id=DEVICE_ID)
    entry.add_to_hass(hass)
    with patch.object(FakeDevice, "connect", False), patch("custom_components.lefant.CONNECT_TIMEOUT", 0.01):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_vacuum_commands(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    for service in ("start", "pause", "stop", "return_to_base", "locate"):
        await hass.services.async_call("vacuum", service, {"entity_id": VACUUM}, blocking=True)
    await hass.services.async_call(
        "vacuum", "set_fan_speed", {"entity_id": VACUUM, "fan_speed": "strong"}, blocking=True
    )
    assert device.sent == [
        {protocol.DP_MODE: "smart", protocol.DP_SWITCH_GO: True},
        {protocol.DP_PAUSE: True},
        {protocol.DP_SWITCH_GO: False},
        {protocol.DP_SWITCH_CHARGE: True},
        {protocol.DP_SEEK: True},
        {protocol.DP_SUCTION: "strong"},
    ]


async def test_fan_speed(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    device.on_dps({protocol.DP_SUCTION: "superStrong"})
    await hass.async_block_till_done()
    state = hass.states.get(VACUUM)
    assert state.attributes["fan_speed"] == "superstrong"
    assert state.attributes["fan_speed_list"] == ["closed", "gentle", "normal", "strong", "superstrong"]
    await hass.services.async_call(
        "vacuum", "set_fan_speed", {"entity_id": VACUUM, "fan_speed": "superstrong"}, blocking=True
    )
    assert device.sent == [{protocol.DP_SUCTION: "superStrong"}]
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "vacuum", "set_fan_speed", {"entity_id": VACUUM, "fan_speed": "turbo"}, blocking=True
        )


async def test_start_resumes_when_paused(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    device.on_dps({protocol.DP_STATUS: "paused"})
    await hass.services.async_call("vacuum", "start", {"entity_id": VACUUM}, blocking=True)
    assert device.sent == [{protocol.DP_PAUSE: False}]


async def test_clean_rooms(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    await hass.services.async_call(
        "vacuum", "send_command",
        {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": ["hall", 1], "repeats": 2}},
        blocking=True,
    )
    assert device.sent == [{protocol.DP_COMMAND: protocol.room_clean_command([2, 1], 2)}]

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "vacuum", "send_command",
            {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": ["garage"]}},
            blocking=True,
        )
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "vacuum", "send_command", {"entity_id": VACUUM, "command": "dance"}, blocking=True
        )


async def test_cleaning_job(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    await hass.services.async_call(
        "vacuum", "send_command",
        {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": [1], "repeats": 2}},
        blocking=True,
    )
    device.on_dps({protocol.DP_STATUS: "part_clean"})
    device.on_dps({protocol.DP_STATUS: "wash_mop"})
    await hass.async_block_till_done()
    job = hass.states.get(VACUUM).attributes["cleaning_job"]
    assert (job["scope"], job["rooms"], job["repeats"], job["mop_washes"]) == ("rooms", [1], 2, 1)
    assert hass.states.get(VACUUM).state == "cleaning"

    assert hass.states.get("sensor.lefant_m5_max_last_cleaning").state == "unavailable"

    device.on_dps({protocol.DP_CLEAN_TIME: 25, protocol.DP_CLEAN_AREA: 12})
    device.on_dps({protocol.DP_STATUS: "goto_charge"})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is None
    assert hass.states.get(VACUUM).state == "returning"
    # without the cloud the last cleaning comes from the robot's counters
    assert hass.states.get("sensor.lefant_m5_max_last_cleaning_duration").state == "25"
    assert hass.states.get("sensor.lefant_m5_max_last_cleaning_area").state == "12"
    assert hass.states.get("sensor.lefant_m5_max_last_cleaning").attributes["rooms"] == ["Kitchen"]


async def test_usage_counters(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    coordinator = entry.runtime_data
    device.on_dps({protocol.DP_CLEAN_TIME: 5})
    device.on_dps({protocol.DP_CLEAN_TIME: 12})
    # a new cleaning starts the robot's counter again from 0
    device.on_dps({protocol.DP_CLEAN_TIME: 3})
    device.on_dps({protocol.DP_WATER: "closed", protocol.DP_CLEAN_TIME: 4})
    device.on_dps({protocol.DP_STATUS: "dust_collection"})
    device.on_dps({protocol.DP_STATUS: "dust_collection"})
    assert coordinator.usage == {"main_brush": 16, "side_brush": 16, "filter": 16, "mop": 15, "dust_bag": 1}

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.lefant_m5_max_main_brush_replaced"}, blocking=True
    )
    assert coordinator.usage["main_brush"] == 0


async def test_fault(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    fake_device[0].on_dps({protocol.DP_FAULT: 0b10})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "error"
    assert hass.states.get("sensor.lefant_m5_max_error").state == "main_brush"
    assert hass.states.get("binary_sensor.lefant_m5_max_problem").state == "on"


async def test_unavailable_after_a_long_disconnection(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]
) -> None:
    fake_device[0].on_connection(False)
    await hass.async_block_till_done()
    state = hass.states.get(VACUUM)
    assert state.state == "docked"
    assert state.attributes["connected"] is False
    assert state.attributes["offline_since"]

    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=11))
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "unavailable"

    fake_device[0].on_connection(True)
    await hass.async_block_till_done()
    state = hass.states.get(VACUUM)
    assert state.state == "docked"
    assert (state.attributes["connected"], state.attributes["offline_since"]) == (True, None)


async def test_disconnection_after_unload(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_unload(entry.entry_id)
    # the device thread reports the disconnection once stopped: no timer is left behind
    fake_device[0].on_connection(False)
    await hass.async_block_till_done()
    assert coordinator._offline_timer is None


def _feed(device: FakeDevice, *pushes: dict) -> None:
    for dps in pushes:
        device.on_dps(dps)


async def test_job_goes_on_after_a_pause(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    """Paused away from the dock the robot falls asleep, then goes on with the same rooms."""
    device = fake_device[0]
    s, t, dock = protocol.DP_STATUS, protocol.DP_CLEAN_TIME, protocol.DP_ON_DOCK
    await hass.services.async_call(
        "vacuum", "send_command",
        {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": [2, 1]}},
        blocking=True,
    )
    _feed(
        device,
        {s: "relocating", t: 0}, {s: "wash_mop"}, {s: "charging"}, {s: "relocating"}, {dock: False},
        {s: "smart", t: 1}, {s: "goto_wash"}, {s: "charging", dock: True},
    )
    await hass.async_block_till_done()
    # charging between two mop washes: still cleaning
    assert hass.states.get(VACUUM).state == "cleaning"
    _feed(device, {s: "wash_mop"}, {s: "paused", dock: False}, {s: "sleep"})
    await hass.async_block_till_done()
    state = hass.states.get(VACUUM)
    assert state.state == "paused"
    started = state.attributes["cleaning_job"]["started"]
    assert state.attributes["cleaning_job"]["rooms"] == [2, 1]

    # the connection drops, the robot is carried back to the dock and goes on from there
    device.on_connection(False)
    device.on_connection(True)
    _feed(
        device,
        {s: "sleep", dock: True}, {s: "wash_mop"}, {s: "paused", dock: False}, {s: "sleep"},
        {s: "sleep", dock: True}, {s: "paused"}, {s: "charging"}, {s: "wash_mop"}, {s: "charging"},
        {s: "smart", dock: False}, {t: 2},
    )
    await hass.async_block_till_done()
    job = hass.states.get(VACUUM).attributes["cleaning_job"]
    assert (job["scope"], job["rooms"], job["started"], job["mop_washes"]) == ("rooms", [2, 1], started, 2)

    # the mop wash after the robot is home is no new cleaning
    _feed(device, {s: "goto_charge"}, {s: "charging", dock: True}, {s: "wash_mop"})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is None
    _feed(device, {s: "drying"})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).state == "docked"
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is None
    assert hass.states.get("sensor.lefant_m5_max_last_cleaning").attributes["rooms"] == ["Hall", "Kitchen"]


@pytest.mark.parametrize("same_push", [True, False])
async def test_new_count_is_a_new_cleaning(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice], same_push: bool
) -> None:
    device = fake_device[0]
    s, t = protocol.DP_STATUS, protocol.DP_CLEAN_TIME
    await hass.services.async_call(
        "vacuum", "send_command",
        {"entity_id": VACUUM, "command": "clean_rooms", "params": {"rooms": [1]}},
        blocking=True,
    )
    _feed(device, {s: "smart", t: 0}, {t: 30}, {s: "goto_charge"}, {s: "charging"})
    # started from the robot's app: the minute counter starts again with the status or right after it
    if same_push:
        _feed(device, {s: "relocating", t: 0})
    else:
        _feed(device, {s: "relocating"}, {t: 0})
    await hass.async_block_till_done()
    job = hass.states.get(VACUUM).attributes["cleaning_job"]
    assert (job["scope"], job["rooms"]) == ("house", [])


async def test_long_charging_ends_the_job(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    s = protocol.DP_STATUS
    _feed(device, {s: "smart", protocol.DP_ON_DOCK: False}, {s: "goto_wash"}, {s: "charging", protocol.DP_ON_DOCK: True})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is not None
    entry.runtime_data._status_since -= DOCK_PAUSE + 1
    device.on_dps({protocol.DP_BATTERY: 90})
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is None
    assert hass.states.get(VACUUM).state == "docked"


async def test_resume_and_stop_an_asleep_job(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    s = protocol.DP_STATUS
    _feed(device, {s: "smart", protocol.DP_ON_DOCK: False}, {s: "paused"}, {s: "sleep"})
    await hass.services.async_call("vacuum", "start", {"entity_id": VACUUM}, blocking=True)
    assert device.sent == [{protocol.DP_PAUSE: False}]

    await hass.services.async_call("vacuum", "stop", {"entity_id": VACUUM}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(VACUUM).attributes["cleaning_job"] is None
    assert hass.states.get(VACUUM).state == "idle"


async def test_base_alerts_kept_away_from_the_dock(
    hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]
) -> None:
    device = fake_device[0]
    bag, clear = protocol.encode(b"\x01\x00\x00\x00\x01\x00\x00"), protocol.encode(b"\x01" + bytes(6))
    sensor = "binary_sensor.lefant_m5_max_dust_bag"
    device.on_dps({protocol.DP_BASE_STATE: bag})
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    # leaving the dock the robot reports all clear before it loses the dock contact
    _feed(device, {protocol.DP_STATUS: "relocating", protocol.DP_BASE_STATE: clear}, {protocol.DP_ON_DOCK: False})
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    # back at the dock the alert comes again within seconds when it is still there
    _feed(device, {protocol.DP_STATUS: "charging", protocol.DP_ON_DOCK: True}, {protocol.DP_BASE_STATE: bag})
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=BASE_SETTLE + 1))
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    _feed(device, {protocol.DP_STATUS: "relocating", protocol.DP_BASE_STATE: clear}, {protocol.DP_ON_DOCK: False})
    # fixed while the robot was away: docked, the robot may send no all clear
    _feed(device, {protocol.DP_STATUS: "charging", protocol.DP_ON_DOCK: True})
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "on"
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=BASE_SETTLE + 1))
    await hass.async_block_till_done()
    assert hass.states.get(sensor).state == "off"


async def test_ws_map(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "lefant/map", "entity_id": VACUUM})
    msg = await client.receive_json()
    assert msg["success"]
    result = msg["result"]
    assert result["entities"]["vacuum"] == VACUUM
    assert result["rooms"] == [{"id": 1, "name": "Kitchen"}, {"id": 2, "name": "Hall"}]
    assert result["map"] is None and not result["editable"]

    await client.send_json_auto_id({"type": "lefant/map", "entity_id": "vacuum.other"})
    assert (await client.receive_json())["error"]["code"] == "not_found"


async def test_ws_rename_and_edit(hass: HomeAssistant, entry: MockConfigEntry, hass_ws_client: WebSocketGenerator) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "lefant/rename_room", "entity_id": VACUUM, "room_id": 2, "name": " Hallway "})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["rooms"][1]["name"] == "Hallway"
    assert entry.options["room_names"] == {"2": "Hallway"}

    await client.send_json_auto_id(
        {"type": "lefant/set_zones", "entity_id": VACUUM, "areas": [], "walls": [[[0, 0], [1, 1]]]}
    )
    msg = await client.receive_json()
    assert msg["error"]["code"] == "edit_failed"
    assert "no map yet" in msg["error"]["message"]


async def test_options_flow(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["description_placeholders"] == {"rooms": "1, 2"}
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"room_1": "Laundry", "room_2": " "}
    )
    assert result["data"] == {"room_names": {"1": "Laundry"}}
    await hass.async_block_till_done()
    assert entry.runtime_data.room_names() == {1: "Laundry", 2: "Hall"}


async def test_dp_journal(hass: HomeAssistant, entry: MockConfigEntry, fake_device: list[FakeDevice]) -> None:
    device = fake_device[0]
    clear = protocol.encode(b"\x01" + bytes(6))
    _feed(
        device,
        {protocol.DP_STATUS: "relocating", protocol.DP_BASE_STATE: clear, "160": "qgADAQABBQ==", protocol.DP_CLEAN_TIME: 3},
        {"160": "qgADAQABBQ=="},
    )
    values = {(e["dp"], e["value"]): e for e in entry.runtime_data._journal.values()}
    # also the dock reading dropped away from the dock, with what the robot was doing
    assert values[(protocol.DP_BASE_STATE, clear)]["status"] == "relocating"
    assert values[("160", "qgADAQABBQ==")]["count"] == 2
    assert not {protocol.DP_STATUS, protocol.DP_CLEAN_TIME} & {dp for dp, _ in values}

    hass.bus.async_fire(EVENT_HOMEASSISTANT_FINAL_WRITE)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert ("160", "qgADAQABBQ==") in {(e["dp"], e["value"]) for e in entry.runtime_data._journal.values()}

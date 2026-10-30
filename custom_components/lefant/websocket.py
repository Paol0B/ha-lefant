"""Websocket API for the dashboard card: map layers, rooms, no-go areas, barriers and map edits."""

from collections.abc import Awaitable, Callable
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import LefantConfigEntry, LefantCoordinator
from .device import LefantDeviceError
from .roborock import async_rename_roborock_room, async_roborock_payload, roborock_entry

POINT = vol.All([vol.Coerce(float)], vol.Length(min=2, max=2))
LINE = vol.All([POINT], vol.Length(min=2, max=2))
AREA = vol.Schema({vol.Required("mode"): vol.In([0, 1, 2]), vol.Required("points"): vol.All([POINT], vol.Length(min=3, max=8))})


@callback
def async_setup_websocket(hass: HomeAssistant) -> None:
    for command in (ws_map, ws_set_zones, ws_split_room, ws_merge_rooms, ws_rename_room):
        websocket_api.async_register_command(hass, command)


def _entry_for_entity(hass: HomeAssistant, entity_id: str) -> LefantConfigEntry | None:
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.config_entry_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.domain != DOMAIN or entry.state is not ConfigEntryState.LOADED:
        return None
    return entry


def _payload(hass: HomeAssistant, entry: LefantConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    prefix = f"{coordinator.device_id}_"
    entities = {
        e.unique_id.removeprefix(prefix): e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.unique_id.startswith(prefix) and not e.disabled_by
    }
    names = coordinator.room_names()
    geometry = coordinator.map_geometry
    rooms_geo = {r["id"]: r for r in geometry.get("rooms", [])}
    rooms = [
        {"id": room_id, "name": name, **{k: v for k, v in rooms_geo.get(room_id, {}).items() if k != "id"}}
        for room_id, name in names.items()
    ]
    editable = "origin" in geometry
    last = coordinator.last_cleaning
    return {
        "entities": entities,
        "rooms": rooms,
        "map": {k: v for k, v in geometry.items() if k not in ("rooms", "origin", "offset")} or None,
        "map_updated": coordinator.map_updated.isoformat() if coordinator.map_updated else None,
        "map_edited": coordinator.map_edited,
        "editable": editable,
        "areas": [
            {"mode": a["mode"], "points": [coordinator.to_map(p) for p in a["points"]]} for a in coordinator.areas
        ] if editable else [],
        "walls": [[coordinator.to_map(p) for p in wall] for wall in coordinator.walls] if editable else [],
        "last_cleaning": {
            "end": last.end.isoformat(),
            "minutes": last.minutes,
            "area": last.area,
            "rooms": last.rooms,
            "names": {str(room_id): coordinator.room_label(room_id) for room_id in last.rooms},
        } if last else None,
    }


@websocket_api.websocket_command({vol.Required("type"): "lefant/map", vol.Required("entity_id"): str})
@websocket_api.async_response
async def ws_map(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if entry := _entry_for_entity(hass, msg["entity_id"]):
        connection.send_result(msg["id"], _payload(hass, entry))
    elif roborock := roborock_entry(hass, msg["entity_id"]):
        connection.send_result(msg["id"], await async_roborock_payload(hass, *roborock))
    else:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no loaded Lefant or Roborock robot")


async def _async_edit(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    action: Callable[[LefantCoordinator], Awaitable[None]],
) -> None:
    entry = _entry_for_entity(hass, msg["entity_id"])
    if entry is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no loaded Lefant robot for this entity")
        return
    try:
        await action(entry.runtime_data)
    except (HomeAssistantError, LefantDeviceError, TimeoutError) as err:
        connection.send_error(msg["id"], "edit_failed", str(err) or "timeout")
        return
    connection.send_result(msg["id"], _payload(hass, entry))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lefant/set_zones",
        vol.Required("entity_id"): str,
        vol.Required("areas"): [AREA],
        vol.Required("walls"): [LINE],
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_set_zones(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _async_edit(hass, connection, msg, lambda c: c.async_set_zones(msg["areas"], msg["walls"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lefant/split_room",
        vol.Required("entity_id"): str,
        vol.Required("room_id"): int,
        vol.Required("line"): LINE,
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_split_room(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _async_edit(hass, connection, msg, lambda c: c.async_split_room(msg["room_id"], msg["line"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lefant/merge_rooms",
        vol.Required("entity_id"): str,
        vol.Required("room_ids"): vol.All([int], vol.Length(min=2, max=2)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_merge_rooms(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    await _async_edit(hass, connection, msg, lambda c: c.async_merge_rooms(msg["room_ids"]))


@websocket_api.websocket_command(
    {
        vol.Required("type"): "lefant/rename_room",
        vol.Required("entity_id"): str,
        vol.Required("room_id"): int,
        vol.Required("name"): vol.All(str, vol.Length(max=40)),
    }
)
@websocket_api.require_admin
@websocket_api.async_response
async def ws_rename_room(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    if roborock := roborock_entry(hass, msg["entity_id"]):
        await async_rename_roborock_room(hass, roborock[1], msg["room_id"], msg["name"])
        connection.send_result(msg["id"], await async_roborock_payload(hass, *roborock))
        return
    await _async_edit(hass, connection, msg, lambda c: c.async_rename_room(msg["room_id"], msg["name"]))

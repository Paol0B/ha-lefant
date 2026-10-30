"""Roborock robot of the same dashboard: map layers, rooms and entity ids for the card.

The data come from the Roborock integration of HA: its config entry keeps a
RoborockCoordinators in runtime_data, with one coordinator per V1 robot.
Room names typed in the card are kept in HA, the robot keeps its own.
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.storage import Store

from . import roborock_map
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

ROBOROCK = "roborock"
# Roborock rooms are segments 16 and up; lower numbers mark floor not assigned to a room
FIRST_SEGMENT = 16
NAMES_KEY = f"{DOMAIN}.roborock_rooms"

# parsed layers per robot, reused while the map file and the room list do not change
_cache: dict[tuple[str, int], tuple[bytes, frozenset[int], dict]] = {}


def roborock_entry(hass: HomeAssistant, entity_id: str) -> tuple[ConfigEntry, Any] | None:
    """Config entry and coordinator of a Roborock vacuum entity."""
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None or entity.platform != ROBOROCK or entity.config_entry_id is None or entity.device_id is None:
        return None
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    device = dr.async_get(hass).async_get(entity.device_id)
    if entry is None or entry.state is not ConfigEntryState.LOADED or device is None:
        return None
    duids = {value for domain, value in device.identifiers if domain == ROBOROCK}
    for coordinator in getattr(entry.runtime_data, "v1", []):
        if coordinator.duid in duids:
            return entry, coordinator
    return None


async def _names(hass: HomeAssistant) -> tuple[Store[dict[str, dict[str, str]]], dict[str, dict[str, str]]]:
    """Room names typed in the card: {"<duid>/<map flag>": {"<segment>": name}}."""
    if NAMES_KEY not in hass.data:
        store: Store[dict[str, dict[str, str]]] = Store(hass, 1, NAMES_KEY)
        hass.data[NAMES_KEY] = (store, await store.async_load() or {})
    return hass.data[NAMES_KEY]


async def _robot_rooms(coordinator: Any, flag: int) -> dict[int, str]:
    """Segment id -> name from the robot; the list cached by the integration can be empty, then ask again."""
    api = coordinator.properties_api
    info = (api.home.home_map_info or {}).get(flag)
    rooms = list(info.rooms) if info else []
    if not rooms and api.maps.current_map == flag:
        try:
            await api.rooms.refresh()
        except Exception as err:  # noqa: BLE001 - any failure of the robot leaves the rooms unnamed
            _LOGGER.debug("Cannot read the Roborock rooms: %s", err)
        rooms = list(api.rooms.rooms or [])
    return {room.segment_id: room.raw_name or "" for room in rooms}


async def async_rename_roborock_room(hass: HomeAssistant, coordinator: Any, room_id: int, name: str) -> None:
    store, names = await _names(hass)
    rooms = names.setdefault(f"{coordinator.duid}/{coordinator.properties_api.maps.current_map}", {})
    if name.strip():
        rooms[str(room_id)] = name.strip()
    else:
        rooms.pop(str(room_id), None)
    await store.async_save(names)


async def async_roborock_payload(hass: HomeAssistant, entry: ConfigEntry, coordinator: Any) -> dict[str, Any]:
    api = coordinator.properties_api
    flag = api.maps.current_map
    duid = coordinator.duid
    slug = coordinator.duid_slug
    suffix = f"_{slug}"
    map_name = next((m.name for m in api.maps.map_info or [] if m.map_flag == flag and m.name), None) or f"Map {flag}"
    entities: dict[str, str] = {}
    for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id):
        if e.disabled_by:
            continue
        if e.unique_id == slug:
            entities["vacuum"] = e.entity_id
        elif e.unique_id == f"{slug}_map_{map_name}":
            entities["map"] = e.entity_id
        elif e.unique_id.endswith(suffix):
            entities[e.unique_id.removesuffix(suffix)] = e.entity_id

    robot_names = await _robot_rooms(coordinator, flag) if flag is not None else {}
    content = (api.home.home_map_content or {}).get(flag) if flag is not None else None
    geometry: dict = {}
    if content is not None and content.raw_api_response:
        raw = content.raw_api_response
        known = frozenset(robot_names)
        cached = _cache.get((duid, flag))
        if cached and cached[0] == raw and cached[1] == known:
            geometry = cached[2]
        else:
            # without a room list from the robot every segment from 16 up is a room
            rooms_filter = set(known) or set(range(FIRST_SEGMENT, 32))
            geometry = await hass.async_add_executor_job(roborock_map.parse, raw, rooms_filter)
            _cache[(duid, flag)] = (raw, known, geometry)

    custom = (await _names(hass))[1].get(f"{duid}/{flag}", {})
    rooms_geo = {r["id"]: r for r in geometry.get("rooms", [])}
    rooms = [
        {
            "id": room_id,
            "name": custom.get(str(room_id)) or robot_names.get(room_id) or f"Room {room_id}",
            **{k: v for k, v in rooms_geo.get(room_id, {}).items() if k != "id"},
        }
        for room_id in sorted(set(robot_names) | set(rooms_geo))
    ]
    record = getattr(api.clean_summary, "last_clean_record", None)
    return {
        "robot": ROBOROCK,
        "entities": entities,
        "rooms": rooms,
        "map": {k: v for k, v in geometry.items() if k not in ("rooms", "origin", "offset")} or None,
        "map_name": map_name,
        "map_updated": coordinator.last_home_update.isoformat() if coordinator.last_home_update else None,
        "map_edited": False,
        "editable": False,
        "renamable": bool(rooms),
        "areas": [],
        "walls": [],
        "last_cleaning": {
            "end": record.end_datetime.isoformat(),
            "minutes": round((record.duration or 0) / 60),
            "area": record.square_meter_area,
            "rooms": None,
        } if record and record.end else None,
    }

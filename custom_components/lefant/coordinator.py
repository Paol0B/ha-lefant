import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import protocol
from .cloud import TuyaCloud, TuyaCloudError
from .const import CONF_DEVICE_ID, CONF_ROOM_NAMES, DOMAIN, MAP_REFRESH_DELAYS, MAP_REFRESH_INTERVAL, MAP_SAME_FLOOR
from .device import LefantDevice

_LOGGER = logging.getLogger(__name__)

# the robot answers a map edit within a few seconds, the new room list follows
EDIT_TIMEOUT = 15
ROOMS_TIMEOUT = 20
# a cleaning is over when the robot heads home or dries the mop; it goes on when the robot comes back to it
JOB_END_STATUSES = protocol.RETURNING_STATUSES | {"drying", "charge_done"}
# the mop washes at the dock come also after the robot is home: they do not start a cleaning
START_STATUSES = protocol.CLEANING_STATUSES - {"wash_mop", "goto_wash"}
# between two mop washes the robot charges for a few seconds: longer, the cleaning is over
DOCK_PAUSE = 120
# seconds after a start in which the robot may still send its minute counter from 0
FRESH_JOB = 60
# the robot drops the connection often while cleaning: entities keep the last state for this long
OFFLINE_GRACE = timedelta(minutes=10)
# the robot passes the base alerts on while it rests on the dock; leaving or away it reports them all clear
BASE_READ_STATUSES = protocol.DOCKED_STATUSES | {"wash_mop"} | protocol.HELD_STATUSES
# an alert still there comes back within 3 s of docking; all clear, the robot may send nothing
BASE_SETTLE = 15
# seconds between a start sent by HA and the robot reporting that it is cleaning
REQUEST_WINDOW = 120
# pushed only on some events (room list, no-go areas, base alerts): saved so that HA starts with them without the cloud
SAVED_DPS = (protocol.DP_ROOMS, protocol.DP_AREAS, protocol.DP_BASE_STATE)

type LefantConfigEntry = ConfigEntry[LefantCoordinator]


class LefantEditError(HomeAssistantError):
    pass


@dataclass(frozen=True)
class LastCleaning:
    end: datetime
    minutes: int
    area: int
    # None: a cleaning started outside HA and known only from the robot's counters
    rooms: list[int] | None


class LefantCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    config_entry: LefantConfigEntry

    def __init__(
        self, hass: HomeAssistant, config_entry: LefantConfigEntry, cloud: TuyaCloud | None
    ) -> None:
        super().__init__(
            hass, _LOGGER, config_entry=config_entry, name=config_entry.title, always_update=False
        )
        self.device_id: str = config_entry.data[CONF_DEVICE_ID]
        self.cloud = cloud
        self.device: LefantDevice | None = None
        self.connected = False
        self.connected_event = asyncio.Event()
        self.offline_since: datetime | None = None
        self._offline_timer: CALLBACK_TYPE | None = None
        self._base_timer: CALLBACK_TYPE | None = None
        self._stopped = False
        self.robot_rooms: dict[int, str] = {}
        self.areas: list[dict[str, Any]] = []
        self.walls: list[list[protocol.RawPoint]] = []
        self.map_image: bytes | None = None
        self.map_geometry: dict[str, Any] = {}
        self.map_updated: datetime | None = None
        self.map_edited = False
        self.last_cleaning: LastCleaning | None = None
        self._cmap: protocol.CleaningMap | None = None
        self._map_record_id: int | None = None
        self._map_lock = asyncio.Lock()
        self._map_retries: list[CALLBACK_TYPE] = []
        self._reports: dict[int, asyncio.Future[bytes]] = {}
        self._rooms_changed = asyncio.Event()
        # cleaning minutes of each part and dust bag emptyings since the last replacement
        self.usage: dict[str, int] = dict.fromkeys((*protocol.WEAR_PARTS, "dust_bag"), 0)
        self._usage_store: Store[dict[str, int]] = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.usage")
        self._clean_minutes: int | None = None
        # map edits shown as a preview on top of the cleaning record they were made on, kept across restarts
        self._edits: list[dict[str, Any]] = []
        self._edits_store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.map_edits")
        # running cleaning: scope ("house", "rooms" started from HA, "other" started elsewhere), rooms in the
        # order sent (the robot cleans them in that order) and passes,
        # start time and mop washes so far; kept across restarts
        self.job: dict[str, Any] | None = None
        # last cleaning closed and the robot's minutes then: it goes on if the robot resumes without a new count
        self._last_job: tuple[dict[str, Any], int | None] | None = None
        self._fresh_until = 0.0
        self._status_since = time.monotonic()
        self._job_store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.job")
        self._requested: tuple[list[int] | None, int, float] | None = None
        # last cleaning record, values of SAVED_DPS and last cleaning: HA starts with them also when the cloud
        # does not answer
        self._map_store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.map")
        self._state_store: Store[dict[str, Any]] = Store(hass, 1, f"{DOMAIN}.{config_entry.entry_id}.state")
        self._saved_dps: dict[str, Any] = {}
        self._saved_last: dict[str, Any] | None = None
        # SAVED_DPS pushed by the robot since HA started: newer than the cloud
        self._pushed: set[str] = set()
        # a split or merge sent by HA is running: the new room list is expected
        self._editing = False

    async def _async_update_data(self) -> dict[str, Any]:
        return self.data or {}

    @property
    def status(self) -> str | None:
        return (self.data or {}).get(protocol.DP_STATUS)

    def room_label(self, room_id: int) -> str:
        """Name of a room, also of one the robot no longer has (merged or split)."""
        custom = self.config_entry.options.get(CONF_ROOM_NAMES, {}).get(str(room_id))
        return self.room_names().get(room_id) or custom or f"Room {room_id}"

    def room_names(self) -> dict[int, str]:
        custom = self.config_entry.options.get(CONF_ROOM_NAMES, {})
        return {
            room_id: custom.get(str(room_id)) or name or f"Room {room_id}"
            for room_id, name in sorted(self.robot_rooms.items())
        }

    @property
    def available(self) -> bool:
        """Connected, or disconnected for less than OFFLINE_GRACE."""
        return self.connected or self._offline_timer is not None

    @callback
    def async_handle_connection(self, connected: bool) -> None:
        if connected:
            self.connected_event.set()
        if connected == self.connected:
            return
        self.connected = connected
        self._cancel_offline_timer()
        self.offline_since = None if connected else dt_util.utcnow()
        if not connected and not self._stopped:
            self._offline_timer = async_call_later(self.hass, OFFLINE_GRACE, self._offline_timeout)
        _LOGGER.info("Robot %s", "connected" if connected else "disconnected")
        self.async_update_listeners()

    @callback
    def _offline_timeout(self, _now: datetime) -> None:
        self._offline_timer = None
        self.async_update_listeners()

    @callback
    def _cancel_offline_timer(self) -> None:
        if self._offline_timer:
            self._offline_timer()
            self._offline_timer = None

    @callback
    def async_stop_connection(self) -> None:
        """The entry unloads: the device thread reports the disconnection afterwards."""
        self._stopped = True
        self._cancel_offline_timer()
        self._cancel_base_timer()

    @callback
    def _cancel_base_timer(self) -> None:
        if self._base_timer:
            self._base_timer()
            self._base_timer = None

    @callback
    def _base_settled(self, _now: datetime) -> None:
        """Docked without a base report: the alerts kept from before are over."""
        self._base_timer = None
        if not (flags := protocol.parse_base_state((self.data or {}).get(protocol.DP_BASE_STATE))) or not any(flags):
            return
        clear = protocol.encode(b"\x01" + bytes(len(flags)))
        self._saved_dps[protocol.DP_BASE_STATE] = clear
        self._save_state()
        self.async_set_updated_data({**(self.data or {}), protocol.DP_BASE_STATE: clear})

    @callback
    def async_handle_dps(self, dps: dict[str, Any]) -> None:
        previous = self.status
        was_docked = (self.data or {}).get(protocol.DP_ON_DOCK)
        if protocol.DP_BASE_STATE in dps and not self._at_base({**(self.data or {}), **dps}):
            # keep what the base said last
            dps = {k: v for k, v in dps.items() if k != protocol.DP_BASE_STATE}
        if protocol.DP_BASE_STATE in dps or dps.get(protocol.DP_ON_DOCK) is False:
            self._cancel_base_timer()
        elif dps.get(protocol.DP_ON_DOCK) is True and was_docked is False and not self._stopped:
            self._cancel_base_timer()
            self._base_timer = async_call_later(self.hass, BASE_SETTLE, self._base_settled)
        if protocol.DP_ROOMS in dps:
            if (rooms := protocol.parse_rooms(dps[protocol.DP_ROOMS])) and rooms != self.robot_rooms:
                if self.robot_rooms and set(rooms) != set(self.robot_rooms) and not self._editing:
                    self._map_changed("the room list changed without an edit from HA")
                self.robot_rooms = rooms
                self._rooms_changed.set()
        for value in dps.values():
            self._handle_frame(protocol.parse_frame(value))
        if flags := protocol.parse_base_state(dps.get(protocol.DP_BASE_STATE)):
            unknown = [i for i, flag in enumerate(flags) if flag and i not in protocol.BASE_FLAGS.values()]
            if unknown:
                _LOGGER.info("Unknown base station alert, bytes %s: %s", unknown, flags.hex(" "))
        if saved := {k: v for k, v in dps.items() if k in SAVED_DPS and v}:
            self._saved_dps.update(saved)
            self._pushed.update(saved)
            self._save_state()
        data = {**(self.data or {}), **dps}
        restarted = self._count_usage(dps, data, previous)
        self._track_job(previous, data, restarted)
        self.async_set_updated_data(data)
        current = self.status
        if previous != current and previous in protocol.CLEANING_STATUSES | protocol.RETURNING_STATUSES and (
            current in protocol.DOCKED_STATUSES
        ):
            self._schedule_map_retries()

    def _handle_frame(self, parsed: tuple[int, bytes] | None) -> None:
        if parsed is None:
            return
        cmd, data = parsed
        try:
            if cmd == protocol.CMD_AREAS_REPORT:
                self.areas, self.walls = protocol.split_zones(protocol.parse_areas(data))
        except (IndexError, ValueError):
            _LOGGER.warning("Cannot parse frame 0x%02x: %s", cmd, data.hex())
            return
        if (future := self._reports.pop(cmd, None)) and not future.done():
            future.set_result(data)

    @staticmethod
    def _at_base(data: dict[str, Any]) -> bool:
        return bool(data.get(protocol.DP_ON_DOCK)) and data.get(protocol.DP_STATUS) in BASE_READ_STATUSES

    def _count_usage(self, dps: dict[str, Any], data: dict[str, Any], previous: str | None) -> bool:
        """Count the usage; True when the robot starts counting the minutes of a new cleaning."""
        changed = restarted = False
        if (minutes := dps.get(protocol.DP_CLEAN_TIME)) is not None:
            last, self._clean_minutes = self._clean_minutes, minutes
            restarted = last is not None and minutes < last
            # DP 16 counts the minutes of the running cleaning and starts again from 0 at the next one
            delta = 0 if last is None else minutes - last if minutes >= last else minutes
            if delta > 0:
                if data.get(protocol.DP_SUCTION) != "closed":
                    for part in ("main_brush", "side_brush", "filter"):
                        self.usage[part] += delta
                if data.get(protocol.DP_MOP_ATTACHED) and data.get(protocol.DP_WATER) != "closed":
                    self.usage["mop"] += delta
                changed = True
        if data.get(protocol.DP_STATUS) == "dust_collection" and previous != "dust_collection":
            self.usage["dust_bag"] += 1
            changed = True
        if changed:
            self._usage_store.async_delay_save(lambda: self.usage, 60)
        return restarted

    async def async_load_usage(self) -> None:
        if stored := await self._usage_store.async_load():
            self.usage.update(stored)
        stored_job = await self._job_store.async_load() or {}
        self.job = stored_job.get("job")
        if last_job := stored_job.get("last_job"):
            self._last_job = (last_job["job"], last_job["minutes"])
        # before the robot connects: a save it triggers would hide the stored values from async_load
        saved = await self._state_store.async_load() or {}
        self._saved_dps = dict(saved.get("dps") or {})
        self._saved_last = saved.get("last_cleaning")

    def note_request(self, rooms: list[int] | None, repeats: int = 1) -> None:
        """Rooms and passes of a cleaning started from HA (None: whole house), matched when the robot starts."""
        self._requested = (rooms, repeats, time.monotonic())

    def _track_job(self, previous: str | None, data: dict[str, Any], restarted: bool) -> None:
        current = data.get(protocol.DP_STATUS)
        now = time.monotonic()
        if current != previous:
            self._status_since = now
        job = self.job
        if restarted:
            # the robot counts the minutes of a new cleaning: the previous one cannot go on
            self._last_job = None
            if now > self._fresh_until:
                job = None
        if job is None:
            if current in START_STATUSES and (current != previous or restarted):
                job = self._open_job(previous, data, now)
        elif current == "wash_mop" and previous != "wash_mop":
            job = {**job, "mop_washes": job["mop_washes"] + 1}
        elif self._job_over(previous, current, data, now):
            self._note_cleaning(job, data)
            self._last_job = (job, data.get(protocol.DP_CLEAN_TIME))
            job = None
        if job is self.job:
            return
        self.job = job
        self._job_store.async_delay_save(self._job_data, 5)

    def _open_job(self, previous: str | None, data: dict[str, Any], now: float) -> dict[str, Any]:
        requested, self._requested = self._requested, None
        if requested and now - requested[2] > REQUEST_WINDOW:
            requested = None
        last, self._last_job = self._last_job, None
        minutes = data.get(protocol.DP_CLEAN_TIME)
        if requested is None and last and (last[1] is None or minutes is None or minutes >= last[1]):
            # the robot goes on with the cleaning it left (asleep after a pause, recharged): same rooms and start
            self._fresh_until = 0.0
            return last[0]
        if requested and requested[0]:
            job = {"scope": "rooms", "rooms": requested[0], "repeats": requested[1]}
        elif requested or data.get(protocol.DP_MODE) == "smart":
            job = {"scope": "house", "rooms": []}
        else:
            job = {"scope": "other", "rooms": []}
        self._fresh_until = now + FRESH_JOB
        # a cleaning already running when HA connects has an unknown start
        return job | {"started": dt_util.utcnow().isoformat() if previous is not None else None, "mop_washes": 0}

    def _job_over(self, previous: str | None, current: str | None, data: dict[str, Any], now: float) -> bool:
        if current in JOB_END_STATUSES:
            return True
        held = protocol.PAUSED_STATUSES | protocol.HELD_STATUSES
        if current in protocol.HELD_STATUSES:
            # paused away from the dock the robot falls asleep: the cleaning goes on when it resumes
            return bool(data.get(protocol.DP_ON_DOCK)) or (previous is not None and previous not in held)
        if current in protocol.DOCKED_STATUSES:
            # carried back to the dock after a pause, or charging for longer than between two mop washes
            return previous in held or now - self._status_since > DOCK_PAUSE
        return False

    @callback
    def end_job(self) -> None:
        """A stop sent by HA: the cleaning is over, also when the robot was already asleep."""
        if self.job is None:
            return
        self._note_cleaning(self.job, self.data or {})
        self.job = self._last_job = None
        self._job_store.async_delay_save(self._job_data, 5)
        self.async_update_listeners()

    def _job_data(self) -> dict[str, Any]:
        last = self._last_job
        return {"job": self.job, "last_job": {"job": last[0], "minutes": last[1]} if last else None}

    def _note_cleaning(self, job: dict[str, Any], data: dict[str, Any]) -> None:
        """Last cleaning from the robot's own counters; the cloud record, when it comes, replaces it."""
        minutes, area = data.get(protocol.DP_CLEAN_TIME), data.get(protocol.DP_CLEAN_AREA)
        if minutes is None or area is None:
            return
        rooms = None if job["scope"] == "other" else list(job["rooms"])
        self.last_cleaning = LastCleaning(dt_util.utcnow(), int(minutes), int(area), rooms)
        self._save_state()

    def _save_state(self) -> None:
        self._state_store.async_delay_save(self._state_data, 10)

    def _state_data(self) -> dict[str, Any]:
        last = self.last_cleaning
        return {
            "dps": self._saved_dps,
            "last_cleaning": {
                "end": last.end.isoformat(), "minutes": last.minutes, "area": last.area, "rooms": last.rooms
            } if last else None,
        }

    @callback
    def _map_changed(self, reason: str) -> None:
        _LOGGER.warning("The robot has a new map (%s): check the no-go areas and the floor plan of the card", reason)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"map_changed_{self.config_entry.entry_id}",
            is_fixable=False,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="map_changed",
            translation_placeholders={"name": self.config_entry.title},
        )

    async def async_reset_usage(self, part: str) -> None:
        self.usage[part] = 0
        await self._usage_store.async_save(self.usage)
        self.async_update_listeners()

    async def async_command(self, dps: dict[str, Any]) -> None:
        assert self.device is not None
        await self.device.async_set(dps)

    async def _async_send_and_wait(self, value: str, report: int) -> bytes:
        future: asyncio.Future[bytes] = self.hass.loop.create_future()
        self._reports[report] = future
        try:
            await self.async_command({protocol.DP_COMMAND: value})
            return await asyncio.wait_for(future, EDIT_TIMEOUT)
        except TimeoutError as err:
            raise LefantEditError("the robot did not confirm the change") from err
        finally:
            self._reports.pop(report, None)

    async def async_load_state(self) -> None:
        """Rooms, no-go areas and base alerts are pushed only on some events: take the last values from the cloud,
        else the ones saved at the last run, then draw the saved map."""
        if self.cloud:
            try:
                shadow = await self.cloud.shadow(self.device_id)
            except TuyaCloudError as err:
                _LOGGER.warning("Cannot read the robot state from the cloud: %s", err)
            else:
                self._saved_dps |= {
                    k: v for k, v in shadow.items() if k in SAVED_DPS and v and k not in self._pushed
                    # the cloud also keeps the all clear sent when the robot leaves the dock
                    and not (k == protocol.DP_BASE_STATE and k in self._saved_dps)
                }
        if not self.robot_rooms and (rooms := protocol.parse_rooms(self._saved_dps.get(protocol.DP_ROOMS))):
            self.robot_rooms = rooms
        self._handle_frame(protocol.parse_frame(self._saved_dps.get(protocol.DP_AREAS)))
        if protocol.DP_BASE_STATE not in (self.data or {}) and self._saved_dps.get(protocol.DP_BASE_STATE):
            self.data = {**(self.data or {}), protocol.DP_BASE_STATE: self._saved_dps[protocol.DP_BASE_STATE]}
        if stored := await self._map_store.async_load():
            await self._async_use_record(stored["record"], base64.b64decode(stored["data"]))
        if (last := self._saved_last) and (end := dt_util.parse_datetime(last["end"])) and (
            self.last_cleaning is None or end > self.last_cleaning.end
        ):
            self.last_cleaning = LastCleaning(end, last["minutes"], last["area"], last["rooms"])
        self._save_state()
        self.async_update_listeners()

    # --- map --------------------------------------------------------------

    def to_map(self, point: protocol.RawPoint) -> list[float]:
        """Robot coordinates (0.5 cm, y up) to the map layers of the card (5 cm pixels, y down)."""
        (ox, oy), (x0, y0) = self.map_geometry["origin"], self.map_geometry["offset"]
        return [round((point[0] + ox) / 10 - x0, 1), round((oy - point[1]) / 10 - y0, 1)]

    def to_robot(self, point: list[float]) -> protocol.RawPoint:
        if "origin" not in self.map_geometry:
            raise LefantEditError("no map yet: run a full cleaning first")
        (ox, oy), (x0, y0) = self.map_geometry["origin"], self.map_geometry["offset"]
        return round((point[0] + x0) * 10 - ox), round(oy - (point[1] + y0) * 10)

    @callback
    def async_start_map_updates(self) -> None:
        if not self.cloud:
            return
        self.config_entry.async_on_unload(
            async_track_time_interval(self.hass, self._async_refresh_map, MAP_REFRESH_INTERVAL)
        )
        self.config_entry.async_on_unload(self._cancel_map_retries)
        self.config_entry.async_create_background_task(
            self.hass, self._async_refresh_map(), "lefant map refresh"
        )

    def _cancel_map_retries(self) -> None:
        for cancel in self._map_retries:
            cancel()
        self._map_retries.clear()

    def _schedule_map_retries(self) -> None:
        self._cancel_map_retries()
        self._map_retries = [
            async_call_later(self.hass, delay, self._async_refresh_map) for delay in MAP_REFRESH_DELAYS
        ]

    async def _async_refresh_map(self, *_: Any) -> None:
        assert self.cloud is not None
        async with self._map_lock:
            try:
                record = await self.cloud.latest_record(self.device_id)
                if not record or record["id"] == self._map_record_id:
                    return
                if protocol.parse_extend(record.get("extend", "")) is None:
                    _LOGGER.warning("Unknown cleaning record format: %s", record.get("extend"))
                    return
                data = await self.cloud.record_map(self.device_id, record["id"])
            except TuyaCloudError as err:
                _LOGGER.warning("Cannot download the cleaning map: %s", err)
                return
            if await self._async_use_record(record, data):
                # the record of this cleaning is in: no need for the other retries
                self._cancel_map_retries()
                await self._map_store.async_save({
                    "record": {k: record.get(k) for k in ("id", "time", "extend")},
                    "data": base64.b64encode(data).decode(),
                })

    async def _async_use_record(self, record: dict[str, Any], data: bytes) -> bool:
        """Map, route and last cleaning of a cleaning record, downloaded or saved in HA."""
        info = protocol.parse_extend(record.get("extend") or "")
        if info is None:
            _LOGGER.warning("Unknown cleaning record format: %s", record.get("extend"))
            return False
        try:
            cmap = await self.hass.async_add_executor_job(protocol.decode_record, data, info.sections)
        except (ValueError, IndexError) as err:
            _LOGGER.warning("Cannot decode cleaning record %s: %s", record["id"], err)
            return False
        # edits change only the room ids, so the edited map has the floor of its record
        if self._cmap is not None and (
            await self.hass.async_add_executor_job(protocol.floor_overlap, self._cmap, cmap) < MAP_SAME_FLOOR
        ):
            self._map_changed(f"record {record['id']} has a different floor")
        self._map_record_id = record["id"]
        self._cmap = cmap
        self.map_edited = False
        stored = await self._edits_store.async_load() or {}
        if stored.get("record") == record["id"]:
            self._edits = stored.get("edits", [])
            for edit in self._edits:
                self._cmap = await self.hass.async_add_executor_job(self._apply_edit, self._cmap, edit)
            self.map_edited = bool(self._edits)
        elif self._edits or stored:
            # a new record carries the robot's own map with the edits in it
            self._edits = []
            await self._edits_store.async_remove()
        self.last_cleaning = LastCleaning(
            end=dt_util.utc_from_timestamp(int(record["time"])),
            minutes=info.minutes,
            area=info.area,
            rooms=cmap.cleaned_rooms,
        )
        await self._async_draw()
        return True

    @staticmethod
    def _apply_edit(cmap: protocol.CleaningMap, edit: dict[str, Any]) -> protocol.CleaningMap:
        if "merge" in edit:
            return protocol.merge_pixels(cmap, set(edit["merge"]), edit["into"])
        (ax, ay), (bx, by) = edit["line"]
        return protocol.split_pixels(cmap, edit["split"], edit["new"], ((ax, ay), (bx, by)), edit.get("rest"))

    async def _async_add_edit(self, edit: dict[str, Any]) -> None:
        assert self._cmap is not None
        self._cmap = await self.hass.async_add_executor_job(self._apply_edit, self._cmap, edit)
        self._edits.append(edit)
        await self._edits_store.async_save({"record": self._map_record_id, "edits": self._edits})
        self.map_edited = True
        await self._async_draw()

    async def _async_draw(self) -> None:
        if self._cmap is None:
            return
        cmap = self._cmap
        # rooms the robot no longer has (merged or split after this record) are drawn as plain floor
        drawn = {v // 4 for v in set(cmap.pixels) if v and v < 240 and not v & 3}
        if self.robot_rooms and (stale := drawn - set(self.robot_rooms)):
            cmap = await self.hass.async_add_executor_job(protocol.merge_pixels, cmap, stale, 0)
        try:
            image = await self.hass.async_add_executor_job(
                partial(protocol.render_map, cmap, self.room_names())
            )
            geometry = await self.hass.async_add_executor_job(protocol.map_geometry, cmap)
        except (ValueError, IndexError, OSError) as err:
            _LOGGER.warning("Cannot draw the map: %s", err)
            return
        self.map_image = image
        self.map_geometry = geometry
        self.map_updated = dt_util.utcnow()
        self.async_update_listeners()

    # --- edits ------------------------------------------------------------

    def _check_idle(self) -> None:
        if not self.connected:
            raise LefantEditError("the robot is not reachable")
        status = self.status
        if status in protocol.CLEANING_STATUSES | protocol.PAUSED_STATUSES | protocol.RETURNING_STATUSES:
            raise LefantEditError("the map can be edited only while the robot is not cleaning")

    async def async_set_zones(self, areas: list[dict[str, Any]], walls: list[list[list[float]]]) -> None:
        self._check_idle()
        raw_areas = [
            {"mode": int(a["mode"]), "points": [self.to_robot(p) for p in a["points"]]} for a in areas
        ]
        raw_walls = [[self.to_robot(p) for p in wall[:2]] for wall in walls]
        try:
            command = protocol.zones_command(raw_areas, raw_walls)
        except ValueError as err:
            raise LefantEditError("too many barriers and no-go areas: remove some") from err
        await self._async_send_and_wait(command, protocol.CMD_AREAS_REPORT)
        self.async_update_listeners()

    async def _async_wait_rooms(self, before: dict[int, str]) -> dict[int, str]:
        if self.robot_rooms != before:
            return self.robot_rooms
        self._rooms_changed.clear()
        try:
            await asyncio.wait_for(self._rooms_changed.wait(), ROOMS_TIMEOUT)
        except TimeoutError:
            _LOGGER.warning("The robot confirmed the room change but did not send the new room list")
        return self.robot_rooms

    async def async_split_room(self, room_id: int, line: list[list[float]]) -> None:
        self._check_idle()
        if room_id not in self.robot_rooms:
            raise LefantEditError(f"unknown room {room_id}")
        before = dict(self.robot_rooms)
        self._editing = True
        try:
            data = await self._async_send_and_wait(
                protocol.split_command(room_id, [self.to_robot(p) for p in line[:2]]), protocol.CMD_SPLIT_REPORT
            )
            if not data or data[0] != 1:
                raise LefantEditError("the robot refused to split the room: draw the line across the whole room")
            after = await self._async_wait_rooms(before)
        finally:
            self._editing = False
        _LOGGER.info("Room %s split: rooms %s -> %s", room_id, sorted(before), sorted(after))
        new_ids = sorted(set(after) - set(before))
        if self._cmap is not None and new_ids:
            (x0, y0) = self.map_geometry["offset"]
            pixel_line = [[p[0] + x0, p[1] + y0] for p in line[:2]]
            edit: dict[str, Any] = {"split": room_id, "new": new_ids[0], "line": pixel_line}
            if room_id not in after and len(new_ids) > 1:
                edit["rest"] = new_ids[1]
            await self._async_add_edit(edit)
        self.async_update_listeners()

    async def async_merge_rooms(self, room_ids: list[int]) -> None:
        self._check_idle()
        if len(room_ids) != 2 or any(r not in self.robot_rooms for r in room_ids):
            raise LefantEditError("choose two existing rooms")
        before = dict(self.robot_rooms)
        self._editing = True
        try:
            data = await self._async_send_and_wait(protocol.merge_command(room_ids), protocol.CMD_MERGE_REPORT)
            if not data or data[0] != 1:
                raise LefantEditError("the robot refused to merge the rooms: they must touch each other")
            after = await self._async_wait_rooms(before)
        finally:
            self._editing = False
        _LOGGER.info("Rooms %s merged: rooms %s -> %s", room_ids, sorted(before), sorted(after))
        gone = set(room_ids) - set(after)
        target = next(iter(sorted(set(after) - set(before))), None) or next(
            (r for r in room_ids if r in after), None
        )
        if self._cmap is not None and gone and target is not None:
            await self._async_add_edit({"merge": sorted(gone), "into": target})
        self.async_update_listeners()

    async def async_rename_room(self, room_id: int, name: str) -> None:
        if room_id not in self.robot_rooms:
            raise LefantEditError(f"unknown room {room_id}")
        names = dict(self.config_entry.options.get(CONF_ROOM_NAMES, {}))
        if name.strip():
            names[str(room_id)] = name.strip()
        else:
            names.pop(str(room_id), None)
        self.hass.config_entries.async_update_entry(
            self.config_entry, options={**self.config_entry.options, CONF_ROOM_NAMES: names}
        )
        await self._async_draw()
        self.async_update_listeners()

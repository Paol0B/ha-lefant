from typing import Any

from homeassistant.components.vacuum import (
    Segment,
    StateVacuumEntity,
    StateVacuumEntityDescription,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import protocol
from .const import DOMAIN
from .coordinator import LefantConfigEntry, LefantCoordinator
from .entity import LefantEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LefantConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LefantVacuum(entry.runtime_data)])


class LefantVacuum(LefantEntity, StateVacuumEntity):
    _attr_name = None
    _attr_translation_key = "vacuum"
    # translation keys must be lowercase, the robot sends "superStrong"
    _attr_fan_speed_list = [speed.lower() for speed in protocol.FAN_SPEEDS]
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.SEND_COMMAND
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.CLEAN_AREA
    )

    def __init__(self, coordinator: LefantCoordinator) -> None:
        super().__init__(coordinator, StateVacuumEntityDescription(key="vacuum"))

    @property
    def activity(self) -> VacuumActivity | None:
        status = self.dp(protocol.DP_STATUS)
        if status is None:
            return None
        if self.dp(protocol.DP_FAULT):
            return VacuumActivity.ERROR
        if status in protocol.CLEANING_STATUSES:
            return VacuumActivity.CLEANING
        if status in protocol.PAUSED_STATUSES:
            return VacuumActivity.PAUSED
        if status in protocol.RETURNING_STATUSES:
            return VacuumActivity.RETURNING
        if status in protocol.DOCKED_STATUSES or self.dp(protocol.DP_ON_DOCK):
            return VacuumActivity.DOCKED
        return VacuumActivity.IDLE

    @property
    def fan_speed(self) -> str | None:
        speed = self.dp(protocol.DP_SUCTION)
        return speed.lower() if isinstance(speed, str) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "status": self.dp(protocol.DP_STATUS),
            "mode": self.dp(protocol.DP_MODE),
            "cleaning_job": self.coordinator.job,
        }

    async def async_start(self) -> None:
        if self.dp(protocol.DP_STATUS) in protocol.PAUSED_STATUSES:
            await self._async_command({protocol.DP_PAUSE: False})
        else:
            self.coordinator.note_request(None)
            await self._async_command({protocol.DP_MODE: "smart", protocol.DP_SWITCH_GO: True})

    async def async_pause(self) -> None:
        await self._async_command({protocol.DP_PAUSE: True})

    async def async_stop(self, **kwargs: Any) -> None:
        await self._async_command({protocol.DP_SWITCH_GO: False})

    async def async_return_to_base(self, **kwargs: Any) -> None:
        await self._async_command({protocol.DP_SWITCH_CHARGE: True})

    async def async_locate(self, **kwargs: Any) -> None:
        await self._async_command({protocol.DP_SEEK: True})

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        speed = next((s for s in protocol.FAN_SPEEDS if s.lower() == fan_speed.lower()), None)
        if speed is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_fan_speed",
                translation_placeholders={"fan_speed": fan_speed, "known": ", ".join(self.fan_speed_list)},
            )
        await self._async_command({protocol.DP_SUCTION: speed})

    async def async_get_segments(self) -> list[Segment]:
        return [Segment(id=str(room_id), name=name) for room_id, name in self.coordinator.room_names().items()]

    async def async_clean_segments(self, segment_ids: list[str], **kwargs: Any) -> None:
        await self._async_clean_rooms([int(segment_id) for segment_id in segment_ids], 1)

    async def _async_clean_rooms(self, room_ids: list[int], repeats: int) -> None:
        known = self.coordinator.robot_rooms
        if not room_ids or any(room_id not in known for room_id in room_ids):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_rooms",
                translation_placeholders={"rooms": ", ".join(map(str, room_ids)), "known": ", ".join(map(str, known))},
            )
        self.coordinator.note_request(room_ids)
        await self._async_command({protocol.DP_COMMAND: protocol.room_clean_command(room_ids, repeats)})

    async def async_send_command(
        self, command: str, params: dict[str, Any] | list[Any] | None = None, **kwargs: Any
    ) -> None:
        params = params or {}
        if command == "clean_rooms" and isinstance(params, dict):
            by_name = {name.casefold(): room_id for room_id, name in self.coordinator.room_names().items()}
            rooms = [
                int(room) if str(room).isdigit() else by_name.get(str(room).casefold(), -1)
                for room in params.get("rooms", [])
            ]
            await self._async_clean_rooms(rooms, int(params.get("repeats", 1)))
        elif command == "set_dp" and isinstance(params, dict):
            await self._async_command({str(params["dp"]): params["value"]})
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_command",
                translation_placeholders={"command": command},
            )

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        if self.registry_entry is None or not self.coordinator.robot_rooms:
            return
        last_seen = self.last_seen_segments
        if last_seen is not None and {s.id for s in last_seen} != {str(r) for r in self.coordinator.robot_rooms}:
            self.async_create_segments_issue()

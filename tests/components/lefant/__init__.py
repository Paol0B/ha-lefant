import asyncio
import base64
from collections.abc import Callable
from typing import Any

from custom_components.lefant import protocol

HOST = "192.0.2.10"
DEVICE_ID = "bf0000000000000000test"
LOCAL_KEY = "test-local-key00"
ENTRY_DATA = {
    "host": HOST,
    "device_id": DEVICE_ID,
    "local_key": LOCAL_KEY,
    "protocol_version": "3.5",
    "region": "eu",
}
CLOUD_DATA = {**ENTRY_DATA, "access_id": "test-access-id", "access_secret": "test-access-secret"}


def rooms_dp(rooms: dict[int, str]) -> str:
    body = b"".join(bytes([room_id, 0, 4, 1, 1, 1, 0x0F, 0, len(name)]) + name.encode() for room_id, name in rooms.items())
    return base64.b64encode(b"\xaa\x00\x00\x00\x00\x01" + bytes([len(rooms)]) + body).decode()


STATUS: dict[str, Any] = {
    protocol.DP_SWITCH_GO: False,
    protocol.DP_PAUSE: False,
    protocol.DP_MODE: "smart",
    protocol.DP_STATUS: "charging",
    protocol.DP_SUCTION: "normal",
    protocol.DP_WATER: "low",
    protocol.DP_CARPET_BOOST: True,
    protocol.DP_RESUME: False,
    protocol.DP_CLEAN_TIME: 0,
    protocol.DP_CLEAN_AREA: 0,
    protocol.DP_BATTERY: 87,
    protocol.DP_ON_DOCK: True,
    protocol.DP_MAC: base64.b64encode(b"\xaa\x00\x07\x01\x12\x34\x56\x78\x9a\xbc\x00").decode(),
    protocol.DP_BASE_STATE: protocol.encode(b"\x01\x00\x01\x00\x00\x00\x00"),
    protocol.DP_MOP_ATTACHED: True,
    protocol.DP_CARPET_DETECTION: True,
    protocol.DP_ROOMS: rooms_dp({1: "Kitchen", 2: "Hall"}),
}


class FakeDevice:
    """Stands in for LefantDevice: connects at once and records the DPs sent."""

    connect = True

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        device_id: str,
        host: str,
        local_key: str,
        version: str,
        on_dps: Callable[[dict[str, Any]], None],
        on_connection: Callable[[bool], None],
    ) -> None:
        self.loop = loop
        self.on_dps = on_dps
        self.on_connection = on_connection
        self.sent: list[dict[str, Any]] = []
        self.last_error: str | None = "no status"
        # answers of the robot to a command: DP updates pushed after it
        self.responder: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None

    def start(self) -> None:
        if self.connect:
            self.loop.call_soon(self.on_connection, True)
            self.loop.call_soon(self.on_dps, dict(STATUS))

    def stop(self) -> None:
        pass

    async def async_set(self, dps: dict[str, Any]) -> None:
        self.sent.append(dps)
        for reply in self.responder(dps) if self.responder else []:
            self.loop.call_soon(self.on_dps, reply)

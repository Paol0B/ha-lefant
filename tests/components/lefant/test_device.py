import asyncio
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

import pytest

from custom_components.lefant.device import LefantDevice, LefantDeviceError


class FakeTuya:
    """tinytuya.Device with a scripted status and scripted pushes."""

    status_reply: dict[str, Any] = {"dps": {"5": "charging"}}
    pushes: list[dict[str, Any]] = []
    instances: list["FakeTuya"] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self.pushes = list(type(self).pushes)
        type(self).instances.append(self)

    def set_socketRetryLimit(self, limit: int) -> None:
        pass

    def set_socketTimeout(self, timeout: float) -> None:
        pass

    def status(self) -> dict[str, Any]:
        return self.status_reply

    def receive(self) -> dict[str, Any] | None:
        time.sleep(0.005)
        return self.pushes.pop(0) if self.pushes else None

    def set_multiple_values(self, dps: dict[str, Any], nowait: bool = False) -> None:
        self.sent.append(dps)

    def heartbeat(self, nowait: bool = False) -> None:
        pass

    def close(self) -> None:
        pass


async def _until(check: Callable[[], bool]) -> None:
    for _ in range(200):
        if check():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.fixture
def tuya() -> Any:
    FakeTuya.instances = []
    with patch("custom_components.lefant.device.tinytuya.Device", FakeTuya):
        yield FakeTuya


def _device(dps: list[dict[str, Any]], connection: list[bool]) -> LefantDevice:
    return LefantDevice(asyncio.get_running_loop(), "id", "192.0.2.10", "key", "3.5", dps.append, connection.append)


async def test_push_and_command(tuya: type[FakeTuya]) -> None:
    dps: list[dict[str, Any]] = []
    connection: list[bool] = []
    with patch.object(tuya, "pushes", [{"dps": {"5": "cleaning"}}]):
        device = _device(dps, connection)
        device.start()
        try:
            await device.async_set({"1": True})
            await _until(lambda: len(dps) == 2)
        finally:
            device.stop()
    await asyncio.sleep(0)
    assert dps == [{"5": "charging"}, {"5": "cleaning"}]
    assert tuya.instances[0].sent == [{"1": True}]
    assert connection == [True, False]


async def test_reconnect_after_lost_connection(tuya: type[FakeTuya]) -> None:
    dps: list[dict[str, Any]] = []
    connection: list[bool] = []
    with patch.object(tuya, "pushes", [{"Err": "905", "Error": "Network Error: Device Unreachable"}]):
        device = _device(dps, connection)
        device.start()
        try:
            await _until(lambda: len(tuya.instances) >= 2 and len(dps) >= 2)
        finally:
            device.stop()
    await asyncio.sleep(0)
    assert connection[:3] == [True, False, True]


async def test_unreachable(tuya: type[FakeTuya]) -> None:
    connection: list[bool] = []
    with patch.object(tuya, "status_reply", {"Err": "905", "Error": "Network Error: Device Unreachable"}):
        device = _device([], connection)
        device.start()
        await _until(lambda: device.last_error is not None)
        command = asyncio.ensure_future(device.async_set({"1": True}))
        await asyncio.sleep(0)
        device.stop()
        with pytest.raises(LefantDeviceError):
            await command
    assert device.last_error == "Network Error: Device Unreachable"
    assert True not in connection

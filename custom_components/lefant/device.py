"""Local Tuya connection to the robot.

tinytuya is blocking, so one worker thread owns the socket: it reads pushed DPs,
sends queued commands and reconnects on errors. Results go back to the event loop.
"""

import asyncio
import logging
import queue
import threading
import time
from collections.abc import Callable
from typing import Any

import tinytuya

_LOGGER = logging.getLogger(__name__)

CONNECTION_ERRORS = {"901", "902", "905", "914"}
RECEIVE_TIMEOUT = 1
CONNECT_TIMEOUT = 5
HEARTBEAT_INTERVAL = 10
FULL_STATUS_INTERVAL = 300
MAX_BACKOFF = 60


class LefantDeviceError(Exception):
    pass


class LefantDevice:
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
        self._loop = loop
        self._device_id = device_id
        self._host = host
        self._local_key = local_key
        self._version = float(version)
        self._on_dps = on_dps
        self._on_connection = on_connection
        self._commands: queue.SimpleQueue[tuple[dict[str, Any], asyncio.Future[None]]] = queue.SimpleQueue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name=f"lefant-{self._host}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=CONNECT_TIMEOUT + RECEIVE_TIMEOUT + 2)

    async def async_set(self, dps: dict[str, Any]) -> None:
        future: asyncio.Future[None] = self._loop.create_future()
        self._commands.put((dps, future))
        await asyncio.wait_for(future, timeout=CONNECT_TIMEOUT * 3)

    def _resolve(self, future: asyncio.Future[None], error: str | None) -> None:
        def _set() -> None:
            if future.done():
                return
            if error:
                future.set_exception(LefantDeviceError(error))
            else:
                future.set_result(None)

        self._loop.call_soon_threadsafe(_set)

    def _emit(self, dps: dict[str, Any]) -> None:
        self._loop.call_soon_threadsafe(self._on_dps, dps)

    def _set_connected(self, connected: bool) -> None:
        self._loop.call_soon_threadsafe(self._on_connection, connected)

    def _fail_pending(self, error: str) -> None:
        while True:
            try:
                _, future = self._commands.get_nowait()
            except queue.Empty:
                return
            self._resolve(future, error)

    def _run(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            dev = tinytuya.Device(
                self._device_id, self._host, self._local_key,
                version=self._version, persist=True, connection_timeout=CONNECT_TIMEOUT,
            )
            dev.set_socketRetryLimit(1)
            try:
                status = dev.status()
                if not status or "dps" not in status:
                    self.last_error = (status or {}).get("Error", "no status")
                    _LOGGER.debug("Connect to %s failed: %s", self._host, self.last_error)
                    self._fail_pending(f"robot unreachable: {self.last_error}")
                    self._stop.wait(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF)
                    continue
                backoff = 1
                self.last_error = None
                self._set_connected(True)
                self._emit(status["dps"])
                self._loop_connected(dev)
            except Exception:  # tinytuya raises plain exceptions on broken frames
                _LOGGER.exception("Unexpected error talking to %s", self._host)
                self._stop.wait(backoff)
            finally:
                dev.close()
                self._set_connected(False)
        self._fail_pending("integration stopped")

    def _loop_connected(self, dev: tinytuya.Device) -> None:
        dev.set_socketTimeout(RECEIVE_TIMEOUT)
        now = time.monotonic()
        next_heartbeat = now + HEARTBEAT_INTERVAL
        next_status = now + FULL_STATUS_INTERVAL
        while not self._stop.is_set():
            while True:
                try:
                    dps, future = self._commands.get_nowait()
                except queue.Empty:
                    break
                result = dev.set_multiple_values(dps, nowait=True)
                if result and result.get("Err") in CONNECTION_ERRORS:
                    self._resolve(future, result.get("Error"))
                    return
                self._resolve(future, None)
            msg = dev.receive()
            if msg:
                if "dps" in msg:
                    self._emit(msg["dps"])
                elif msg.get("Err") in CONNECTION_ERRORS:
                    self.last_error = msg.get("Error")
                    _LOGGER.debug("Connection to %s lost: %s", self._host, msg)
                    return
            now = time.monotonic()
            if now >= next_heartbeat:
                result = dev.heartbeat(nowait=True)
                if result and result.get("Err") in CONNECTION_ERRORS:
                    self.last_error = result.get("Error")
                    return
                next_heartbeat = now + HEARTBEAT_INTERVAL
            if now >= next_status:
                status = dev.status()
                if not status or "dps" not in status:
                    self.last_error = (status or {}).get("Error", "no status")
                    return
                self._emit(status["dps"])
                next_status = now + FULL_STATUS_INTERVAL

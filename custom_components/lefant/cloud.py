"""Tuya OpenAPI client for a cloud project linked to the Smart Life account."""

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import aiohttp

from .const import REGIONS

TIMEOUT = aiohttp.ClientTimeout(total=30)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
TOKEN_INVALID_CODES = {1010, 1011}


class TuyaCloudError(Exception):
    pass


class TuyaCloudAuthError(TuyaCloudError):
    pass


class TuyaCloud:
    def __init__(
        self, session: aiohttp.ClientSession, region: str, access_id: str, access_secret: str
    ) -> None:
        self._session = session
        self._base = REGIONS[region]
        self._access_id = access_id
        self._secret = access_secret.encode()
        self._token = ""
        self._token_expires = 0.0

    def _headers(self, path: str, token: str) -> dict[str, str]:
        t = str(int(time.time() * 1000))
        string_to_sign = f"GET\n{EMPTY_SHA256}\n\n{path}"
        sign = hmac.new(
            self._secret, (self._access_id + token + t + string_to_sign).encode(), hashlib.sha256
        ).hexdigest().upper()
        headers = {"client_id": self._access_id, "sign": sign, "t": t, "sign_method": "HMAC-SHA256"}
        if token:
            headers["access_token"] = token
        return headers

    async def _get(self, path: str, token: str) -> Any:
        try:
            async with self._session.get(
                self._base + path, headers=self._headers(path, token), timeout=TIMEOUT
            ) as resp:
                body = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise TuyaCloudError(f"{path}: {err!r}") from err
        if not body.get("success"):
            code = body.get("code")
            err_cls = TuyaCloudAuthError if code in TOKEN_INVALID_CODES or code == 1004 else TuyaCloudError
            raise err_cls(f"{path}: {code} {body.get('msg')}")
        return body.get("result")

    async def _ensure_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        result = await self._get("/v1.0/token?grant_type=1", "")
        self._token = result["access_token"]
        self._token_expires = time.time() + int(result["expire_time"])
        return self._token

    async def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if params:
            path = f"{path}?{urlencode(sorted(params.items()))}"
        try:
            return await self._get(path, await self._ensure_token())
        except TuyaCloudAuthError:
            # the token can be revoked before it expires: retry once with a new one
            self._token = ""
            return await self._get(path, await self._ensure_token())

    async def device(self, device_id: str) -> dict[str, Any]:
        return await self.get(f"/v1.0/devices/{device_id}")

    async def shadow(self, device_id: str) -> dict[str, Any]:
        result = await self.get(f"/v2.0/cloud/thing/{device_id}/shadow/properties")
        return {str(p["dp_id"]): p["value"] for p in result.get("properties", []) if "value" in p}

    async def latest_record(self, device_id: str) -> dict[str, Any] | None:
        result = await self.get(
            f"/v1.0/users/sweepers/file/{device_id}/list",
            {"file_type": "pic", "page_no": 1, "page_size": 5},
        )
        records = sorted(result.get("datas") or [], key=lambda r: int(r["time"]), reverse=True)
        return records[0] if records else None

    async def record_map(self, device_id: str, record_id: int) -> bytes:
        result = await self.get(f"/v1.0/users/sweepers/file/{device_id}/download", {"id": record_id})
        url = result.get("app_map")
        if not url:
            raise TuyaCloudError(f"record {record_id} has no map")
        try:
            async with self._session.get(url, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                return await resp.read()
        except (aiohttp.ClientError, TimeoutError) as err:
            raise TuyaCloudError(f"map download: {err!r}") from err

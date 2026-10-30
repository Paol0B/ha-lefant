import hashlib
import hmac

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.lefant.cloud import TuyaCloud, TuyaCloudAuthError, TuyaCloudError

BASE = "https://openapi.tuyaeu.com"
DEVICE = "bf0000000000000000test"
TOKEN = {"success": True, "result": {"access_token": "tok1", "expire_time": 7200}}


def cloud(hass: HomeAssistant) -> TuyaCloud:
    return TuyaCloud(async_get_clientsession(hass), "eu", "test-id", "test-secret")


async def test_signed_request(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/v1.0/token?grant_type=1", json=TOKEN)
    aioclient_mock.get(f"{BASE}/v1.0/devices/{DEVICE}", json={"success": True, "result": {"name": "Robot"}})
    client = cloud(hass)
    assert await client.device(DEVICE) == {"name": "Robot"}
    assert await client.device(DEVICE) == {"name": "Robot"}
    # one token for both calls
    assert aioclient_mock.call_count == 3

    headers = aioclient_mock.mock_calls[1][3]
    path = f"/v1.0/devices/{DEVICE}"
    string_to_sign = f"GET\n{hashlib.sha256(b'').hexdigest()}\n\n{path}"
    expected = hmac.new(
        b"test-secret", f"test-idtok1{headers['t']}{string_to_sign}".encode(), hashlib.sha256
    ).hexdigest().upper()
    assert headers["sign"] == expected
    assert headers["access_token"] == "tok1"


async def test_token_renewed_once(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/v1.0/token?grant_type=1", json=TOKEN)
    aioclient_mock.get(f"{BASE}/v1.0/devices/{DEVICE}", json={"success": False, "code": 1010, "msg": "token invalid"})
    with pytest.raises(TuyaCloudAuthError):
        await cloud(hass).device(DEVICE)
    assert aioclient_mock.call_count == 4


async def test_error(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/v1.0/token?grant_type=1", json=TOKEN)
    aioclient_mock.get(f"{BASE}/v1.0/devices/{DEVICE}", json={"success": False, "code": 1106, "msg": "permission deny"})
    with pytest.raises(TuyaCloudError, match="1106"):
        await cloud(hass).device(DEVICE)


async def test_shadow_and_records(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(f"{BASE}/v1.0/token?grant_type=1", json=TOKEN)
    aioclient_mock.get(
        f"{BASE}/v2.0/cloud/thing/{DEVICE}/shadow/properties",
        json={"success": True, "result": {"properties": [{"dp_id": 183, "value": "x"}, {"dp_id": 5}]}},
    )
    aioclient_mock.get(
        f"{BASE}/v1.0/users/sweepers/file/{DEVICE}/list?file_type=pic&page_no=1&page_size=5",
        json={"success": True, "result": {"datas": [{"id": 1, "time": "100"}, {"id": 2, "time": "200"}]}},
    )
    aioclient_mock.get(
        f"{BASE}/v1.0/users/sweepers/file/{DEVICE}/download?id=2",
        json={"success": True, "result": {"app_map": "https://files.example.com/map.bin"}},
    )
    aioclient_mock.get("https://files.example.com/map.bin", content=b"MAP")
    client = cloud(hass)
    assert await client.shadow(DEVICE) == {"183": "x"}
    record = await client.latest_record(DEVICE)
    assert record == {"id": 2, "time": "200"}
    assert await client.record_map(DEVICE, 2) == b"MAP"

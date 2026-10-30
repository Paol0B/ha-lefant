from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "lefant"
MANUFACTURER = "Lefant"

CONF_DEVICE_ID = "device_id"
CONF_LOCAL_KEY = "local_key"
CONF_PROTOCOL_VERSION = "protocol_version"
CONF_ACCESS_ID = "access_id"
CONF_ACCESS_SECRET = "access_secret"
CONF_REGION = "region"
CONF_ROOM_NAMES = "room_names"

DEFAULT_PROTOCOL_VERSION = "3.5"
PROTOCOL_VERSIONS = ["3.3", "3.4", "3.5"]
DEFAULT_REGION = "eu"
REGIONS = {
    "eu": "https://openapi.tuyaeu.com",
    "weu": "https://openapi-weaz.tuyaeu.com",
    "us": "https://openapi.tuyaus.com",
    "eus": "https://openapi-ueaz.tuyaus.com",
    "cn": "https://openapi.tuyacn.com",
    "in": "https://openapi.tuyain.com",
}

CONNECT_TIMEOUT = 20
MAP_REFRESH_INTERVAL = timedelta(minutes=30)
# the cleaning record reaches the cloud some time after the robot docks
MAP_REFRESH_DELAYS = (60, 180, 600)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.IMAGE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.VACUUM,
]

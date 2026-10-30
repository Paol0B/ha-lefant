import json
import struct
from pathlib import Path

import pytest

INTEGRATION = Path(__file__).parents[3] / "custom_components" / "lefant"


@pytest.mark.parametrize(
    ("name", "size"),
    [("icon.png", 256), ("icon@2x.png", 512), ("dark_icon.png", 256), ("dark_icon@2x.png", 512)],
)
def test_brand_icons(name: str, size: int) -> None:
    head = (INTEGRATION / "brand" / name).read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", head[16:24]) == (size, size)


def test_english_translation_matches_strings() -> None:
    strings = json.loads((INTEGRATION / "strings.json").read_text())
    assert json.loads((INTEGRATION / "translations" / "en.json").read_text()) == strings


def test_hacs_minimum_version_matches_readme() -> None:
    hacs = json.loads((INTEGRATION.parents[1] / "hacs.json").read_text())
    readme = (INTEGRATION.parents[1] / "README.md").read_text()
    major_minor = hacs["homeassistant"].rsplit(".", 1)[0]
    assert f"Home Assistant {major_minor} or newer" in readme


def test_card_resource_version_matches_manifest() -> None:
    version = json.loads((INTEGRATION / "manifest.json").read_text())["version"]
    readme = (INTEGRATION.parents[1] / "README.md").read_text()
    assert f"/lefant_static/lefant-vacuum-card.js?v={version}" in readme

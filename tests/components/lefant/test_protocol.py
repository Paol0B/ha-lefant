import base64
import struct

import pytest

from custom_components.lefant import protocol


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def lz4_literals(data: bytes) -> bytes:
    """LZ4 block made of one literal run."""
    if len(data) < 15:
        return bytes([len(data) << 4]) + data
    rest = len(data) - 15
    return b"\xf0" + b"\xff" * (rest // 255) + bytes([rest % 255]) + data


def test_frame_round_trip() -> None:
    value = protocol.encode(b"\x14\x01\x02\x03\x05")
    assert base64.b64decode(value) == b"\xaa\x00\x05\x14\x01\x02\x03\x05\x1f"
    assert protocol.parse_frame(value) == (0x14, b"\x01\x02\x03\x05")


def test_frame_too_long() -> None:
    with pytest.raises(ValueError):
        protocol.frame(bytes(256))


def test_parse_frame_version_1() -> None:
    assert protocol.parse_frame(b64(b"\xaa\x01\x00\x00\x00\x03\x1b\x00\x07\x00")) == (0x1B, b"\x00\x07")


@pytest.mark.parametrize("value", [None, 7, "", "not base64!", b64(b"\xaa\x00"), b64(b"\xab\x00\x01\x14\x14"), b64(b"\xaa\x00\x09\x14\x14")])
def test_parse_frame_rejects(value: object) -> None:
    assert protocol.parse_frame(value) is None  # type: ignore[arg-type]


def test_room_clean_command() -> None:
    assert protocol.parse_frame(protocol.room_clean_command([3, 5], 2)) == (0x14, b"\x02\x02\x03\x05")


def test_areas_round_trip() -> None:
    areas = [{"mode": 1, "points": [(-10, 20), (30, 20), (30, -40)]}]
    cmd, data = protocol.parse_frame(protocol.zones_command(areas, [[(0, 0), (5, -5)]]))
    assert cmd == protocol.CMD_AREAS_SET
    parsed = protocol.parse_areas(data)
    assert parsed == [
        {"mode": 1, "points": [(-10, 20), (30, 20), (30, -40)]},
        {"mode": protocol.WALL_MODE, "points": [(0, 0), (5, -5)]},
    ]
    assert protocol.split_zones(parsed) == ([parsed[0]], [[(0, 0), (5, -5)]])


def test_zones_command_too_many() -> None:
    areas = [{"mode": 0, "points": [(0, 0)] * 8}] * 10
    with pytest.raises(ValueError):
        protocol.zones_command(areas, [])


def test_split_and_merge_commands() -> None:
    assert protocol.parse_frame(protocol.split_command(4, [(1, -1), (2, 3)])) == (
        0x1C, b"\x04\x00\x01\xff\xff\x00\x02\x00\x03"
    )
    assert protocol.parse_frame(protocol.merge_command([4, 6])) == (0x1E, b"\x04\x06")


def test_parse_rooms() -> None:
    def room(room_id: int, name: bytes) -> bytes:
        return bytes([room_id, 0, 4, 1, 1, 1, 0x0F, 0, len(name)]) + name

    data = b"\xaa\x00\x00\x00\x00\x01\x02" + room(3, b"Kitchen") + room(5, "Café".encode())
    assert protocol.parse_rooms(b64(data)) == {3: "Kitchen", 5: "Café"}


def test_parse_rooms_truncated() -> None:
    data = b"\xaa\x00\x00\x00\x00\x01\x03" + bytes([3, 0, 4, 1, 1, 1, 0x0F, 0, 1]) + b"A"
    assert protocol.parse_rooms(b64(data)) == {3: "A"}
    assert protocol.parse_rooms(None) == {}
    assert protocol.parse_rooms("%%") == {}


def test_parse_mac() -> None:
    assert protocol.parse_mac(b64(b"\xaa\x00\x07\x01\x12\x34\x56\x78\x9a\xbc\x00")) == "12:34:56:78:9a:bc"
    assert protocol.parse_mac(b64(b"\xaa\x00")) is None
    assert protocol.parse_mac(None) is None


def test_parse_base_state() -> None:
    value = protocol.encode(b"\x01\x00\x01\x00\x01\x00\x00")
    flags = protocol.parse_base_state(value)
    assert flags is not None
    assert {name: bool(flags[i]) for name, i in protocol.BASE_FLAGS.items()} == {
        "clean_water": False, "dirty_water": True, "dust_bag": True
    }
    assert protocol.parse_base_state(protocol.encode(b"\x02\x00")) is None


def test_active_faults() -> None:
    assert protocol.active_faults(None) == []
    assert protocol.active_faults(0b1000001) == ["side_brush", "bumper"]
    assert protocol.active_faults(1 << 9) == ["fault_9"]


def test_parse_extend() -> None:
    info = protocol.parse_extend("0_0_0_42_31_1000_80_0_12")
    assert info == protocol.RecordInfo(minutes=42, area=31, sections=[1000, 80, 0, 12])
    assert protocol.parse_extend("1_2_3") is None
    assert protocol.parse_extend("0_0_0_x_31_1000_80_0_12") is None


def test_lz4_match() -> None:
    # 2 literals "ab", then a match 2 bytes back of length 4
    assert protocol._lz4_block(b"\x20ab\x02\x00", 6) == b"ababab"
    with pytest.raises(ValueError):
        protocol._lz4_block(b"\x20ab\x05\x00", 6)
    with pytest.raises(ValueError):
        protocol._lz4_block(b"\x20ab", 6)


# 6 x 4 map: wall row on top, room 1 (value 4) on the left, room 2 (value 8) on the right, unknown row at the bottom
PIXELS = bytes(
    [0xF0] * 6
    + [4, 4, 4, 8, 8, 8]
    + [4, 4, 0, 0, 8, 8]
    + [protocol.MAP_UNKNOWN] * 6
)


def record_file(pixels: bytes = PIXELS, route: list[tuple[int, int]] | None = None, rooms: list[int] | None = None) -> tuple[bytes, list[int]]:
    header = b"\x00" * 4 + struct.pack(">HHHH", 6, 4, 30, 20) + b"\x00" * 12
    map_part = header + lz4_literals(pixels)
    points = route or []
    route_part = b"\x00" * 7 + struct.pack(">H", len(points)) + b"\x00" * 4 + b"".join(
        struct.pack(">hh", x, y) for x, y in points
    )
    rooms_part = protocol.frame(bytes([0x15, 1, len(rooms or []), *(rooms or [])]))
    return map_part + route_part + rooms_part, [len(map_part), len(route_part), 0, len(rooms_part)]


def test_decode_record() -> None:
    data, sections = record_file(route=[(0, 0), (10, -10), (0, 0)], rooms=[1, 2])
    cmap = protocol.decode_record(data, sections)
    assert (cmap.width, cmap.height, cmap.origin) == (6, 4, (30, 20))
    assert cmap.pixels == PIXELS
    assert cmap.route == [(0, 0), (10, -10)]
    assert cmap.cleaned_rooms == [1, 2]


@pytest.mark.parametrize("data", [b"\x00" * 10, b"\x00" * 4 + struct.pack(">HHHH", 0, 4, 0, 0) + b"\x00" * 12])
def test_decode_record_rejects(data: bytes) -> None:
    with pytest.raises(ValueError):
        protocol.decode_record(data, [])


def test_map_geometry() -> None:
    cmap = protocol.CleaningMap(6, 4, (30, 20), PIXELS, route=[(0, 0), (10, -10)])
    geo = protocol.map_geometry(cmap)
    assert (geo["width"], geo["height"], geo["offset"]) == (6, 3, [0, 0])
    assert geo["walls"] == "M0 0h6v1h-6z"
    assert geo["floor"] == "M2 2h2v1h-2z"
    rooms = {r["id"]: r for r in geo["rooms"]}
    assert set(rooms) == {1, 2}
    assert rooms[1]["area"] == round(5 * protocol.PIXEL_AREA_M2, 1)
    assert rooms[1]["label"] == [1.5, 1.5]
    assert geo["route"] == "M3.0 2.0L4.0 3.0"
    assert geo["dock"] == [3.0, 2.0]


def test_map_geometry_empty() -> None:
    assert protocol.map_geometry(protocol.CleaningMap(2, 1, (0, 0), bytes([255, 255]))) == {}


def test_merge_and_split_pixels() -> None:
    cmap = protocol.CleaningMap(6, 4, (30, 20), PIXELS)
    merged = protocol.merge_pixels(cmap, {2}, 1)
    assert 8 not in merged.pixels and merged.pixels.count(4) == 10
    # vertical line at x = 0.5 across room 1: the 2 pixels on the left are the smaller side
    split = protocol.split_pixels(cmap, 1, 3, ((0.5, 0), (0.5, 4)))
    assert split.pixels.count(12) == 2 and split.pixels.count(4) == 3


def test_render_map() -> None:
    png = protocol.render_map(protocol.CleaningMap(6, 4, (30, 20), PIXELS, route=[(0, 0), (10, -10)]), {1: "Kitchen"})
    assert png.startswith(b"\x89PNG")

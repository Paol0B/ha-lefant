import gzip
import struct

from custom_components.lefant import roborock_map

FILE_HEADER = 0x14


def block(block_type: int, data: bytes, header_extra: bytes = b"") -> bytes:
    header_length = 8 + len(header_extra)
    return struct.pack("<HHi", block_type, header_length, len(data)) + header_extra + data


def map_file(robot: bool = True) -> bytes:
    # 4 x 3 image, row 0 at the bottom: room 16 (0x87) on the left, wall column, floor on the right
    w, h, top, left = 4, 3, 100, 200
    image = bytes([0x87, 0x87, 0x01, 0xFF] * h)
    header = b"rr" + struct.pack("<H", FILE_HEADER) + b"\x00" * (FILE_HEADER - 4)
    path_points = struct.pack("<HHHH", 10050, 5050, 10100, 5100)
    blocks = [
        block(roborock_map.BLOCK_CHARGER, struct.pack("<ii", 10000, 5100)),
        block(roborock_map.BLOCK_IMAGE, image, struct.pack("<iiii", top, left, h, w)),
        block(roborock_map.BLOCK_PATH, path_points, b"\x00" * 12),
    ]
    if robot:
        blocks.append(block(roborock_map.BLOCK_ROBOT, struct.pack("<ii", 10075, 5075)))
    return header + b"".join(blocks)


def test_parse() -> None:
    geo = roborock_map.parse(gzip.compress(map_file()), {16})
    assert (geo["width"], geo["height"]) == (4, 3)
    assert [r["id"] for r in geo["rooms"]] == [16]
    assert geo["walls"] == "M2 0h1v3h-1z"
    assert geo["floor"] == "M3 0h1v3h-1z"
    assert geo["dock"] == [0.0, 1.0]
    assert geo["route"] == "M1.0 2.0L2.0 1.0"
    assert geo["robot"] == [1.5, 1.5]


def test_parse_room_outside_filter_is_floor() -> None:
    geo = roborock_map.parse(map_file(robot=False), {17})
    assert geo["rooms"] == []
    assert "robot" not in geo


def test_parse_without_image() -> None:
    assert roborock_map.parse(b"rr" + struct.pack("<H", 4)) == {}

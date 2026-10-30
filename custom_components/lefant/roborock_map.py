"""Roborock map files, as kept by the Roborock integration of HA, turned into the map layers of the card.

Block layout from vacuum-map-parser-roborock: a file header, then blocks of
<type int16> <header length int16> <data length int32> ... Positions are in mm,
image pixels are 5 cm like the Lefant maps, with row 0 at the bottom.
"""

import gzip
from dataclasses import dataclass

from .protocol import MAP_UNKNOWN, CleaningMap, map_geometry

BLOCK_CHARGER = 1
BLOCK_IMAGE = 2
BLOCK_PATH = 3
BLOCK_ROBOT = 8
MM_PER_PIXEL = 50
# Roborock pixels: 0 outside, 1 wall, 7 scanned, 255 floor; low bits 0b111 = room number in the high 5 bits
PIXEL_OUTSIDE, PIXEL_WALL, PIXEL_SCAN, PIXEL_FLOOR = 0x00, 0x01, 0x07, 0xFF
# same pixel values as a Lefant map, so protocol.map_geometry draws both
LEFANT_WALL = 0xF0
LEFANT_FLOOR = 0x00


@dataclass
class _Image:
    top: int
    left: int
    width: int
    height: int
    data: bytes


def _int16(raw: bytes, pos: int) -> int:
    return int.from_bytes(raw[pos:pos + 2], "little")


def _int32(raw: bytes, pos: int) -> int:
    return int.from_bytes(raw[pos:pos + 4], "little", signed=True)


def _pixel(value: int, rooms: set[int] | None) -> int:
    if value == PIXEL_OUTSIDE:
        return MAP_UNKNOWN
    if value in (PIXEL_FLOOR, PIXEL_SCAN):
        return LEFANT_FLOOR
    if value == PIXEL_WALL or value & 0x07 in (0, 1):
        return LEFANT_WALL
    if value & 0x07 == 0x07 and (rooms is None or value >> 3 in rooms):
        return (value >> 3) * 4
    return LEFANT_FLOOR


def parse(raw: bytes, rooms: set[int] | None = None) -> dict:
    """Card layers of a Roborock map: the dict of protocol.map_geometry plus the robot position.

    Room pixels outside `rooms` (areas the robot has not assigned to a room) are drawn as floor.
    """
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    image: _Image | None = None
    charger = robot = None
    path: list[tuple[int, int]] = []
    pos = _int16(raw, 0x02)
    while pos + 8 <= len(raw):
        block_type = _int16(raw, pos)
        header_length = _int16(raw, pos + 0x02)
        data_length = _int32(raw, pos + 0x04)
        data = raw[pos + header_length:pos + header_length + data_length]
        if block_type == BLOCK_IMAGE:
            header = raw[pos:pos + header_length]
            image = _Image(
                top=_int32(header, header_length - 16),
                left=_int32(header, header_length - 12),
                height=_int32(header, header_length - 8),
                width=_int32(header, header_length - 4),
                data=data,
            )
        elif block_type == BLOCK_CHARGER:
            charger = (_int32(data, 0), _int32(data, 4))
        elif block_type == BLOCK_ROBOT:
            robot = (_int32(data, 0), _int32(data, 4))
        elif block_type == BLOCK_PATH:
            points = raw[pos + 0x14:pos + 0x14 + data_length]
            path = [(_int16(points, i), _int16(points, i + 2)) for i in range(0, len(points) - 3, 4)]
        pos += data_length + raw[pos + 0x02]
    if image is None or not image.width or not image.height:
        return {}

    w, h = image.width, image.height

    def to_pixel(point: tuple[int, int]) -> tuple[float, float]:
        """mm to pixels of the full image, y down."""
        return point[0] / MM_PER_PIXEL - image.left, h - (point[1] / MM_PER_PIXEL - image.top)

    pixels = image.data.translate(bytes(_pixel(v, rooms) for v in range(256)))
    rows = [pixels[r * w:(r + 1) * w] for r in range(h - 1, -1, -1)]
    dock = to_pixel(charger) if charger else (w / 2, h / 2)
    # the Lefant layout counts the route from the dock in 0.5 cm units with y up
    ox, oy = round(dock[0] * 10), round(dock[1] * 10)
    route = [(round(px * 10) - ox, oy - round(py * 10)) for px, py in map(to_pixel, path)]
    geometry = map_geometry(CleaningMap(width=w, height=h, origin=(ox, oy), pixels=b"".join(rows), route=route))
    if geometry and robot:
        x0, y0 = geometry["offset"]
        rx, ry = to_pixel(robot)
        geometry["robot"] = [round(rx - x0, 1), round(ry - y0, 1)]
    return geometry

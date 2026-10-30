"""Lefant M5 Max data points and the Tuya laser sweeper formats (raw frames, cleaning record maps)."""

import base64
import io
import struct
from dataclasses import dataclass, field, replace

DP_SWITCH_GO = "1"
DP_PAUSE = "2"
DP_SWITCH_CHARGE = "3"
DP_MODE = "4"
DP_STATUS = "5"
DP_SUCTION = "9"
DP_WATER = "10"
DP_CARPET_BOOST = "14"
DP_RESUME = "15"
DP_CLEAN_TIME = "16"
DP_CLEAN_AREA = "17"
DP_BATTERY = "23"
DP_SEEK = "27"
DP_AREAS = "101"
DP_COMMAND = "113"
DP_FAULT = "114"
DP_ON_DOCK = "125"
DP_MAC = "155"
DP_BASE_STATE = "158"
DP_ALARM_CODE = "164"
DP_MOP_ATTACHED = "171"
DP_CARPET_DETECTION = "172"
DP_ROOMS = "183"

STATUSES = [
    "standby", "smart", "zone_clean", "part_clean", "cleaning", "paused",
    "goto_pos", "pos_arrived", "pos_unarrive", "goto_charge", "charging",
    "charge_done", "sleep", "relocating", "relocating_recharge",
    "recharing_paused", "fastmaping", "fastmaping_paused", "dust_collection",
    "wash_mop", "goto_wash", "wash_paused", "drying",
    "continuity_clear_charging", "relocating_pause",
]
CLEANING_STATUSES = frozenset({
    "smart", "zone_clean", "part_clean", "cleaning", "goto_pos", "pos_arrived",
    "relocating", "fastmaping", "wash_mop", "goto_wash",
})
PAUSED_STATUSES = frozenset({
    "paused", "recharing_paused", "fastmaping_paused", "wash_paused", "relocating_pause",
})
RETURNING_STATUSES = frozenset({"goto_charge", "relocating_recharge"})
DOCKED_STATUSES = frozenset({
    "charging", "charge_done", "drying", "dust_collection", "continuity_clear_charging",
})

FAN_SPEEDS = ["closed", "gentle", "normal", "strong", "superStrong"]
WATER_LEVELS = ["closed", "low", "middle", "high"]
# DP 114 bits, from the product model; the higher bits are not documented
FAULTS = ["side_brush", "main_brush", "left_wheel", "right_wheel", "dust_bin", "cliff_sensor", "bumper"]
# DP 158 data bytes, 1 = alert: found on 2026-10-28 by taking each part out of the base.
# Bytes 2, 4 and 5 never changed; removing the detergent container changed nothing.
BASE_FLAGS = {"clean_water": 0, "dirty_water": 1, "dust_bag": 3}
# parts counted by HA: the robot does not report their wear
WEAR_PARTS = ("main_brush", "side_brush", "filter", "mop")

MAP_UNKNOWN = 255
# 5 cm pixels: the room areas of a record add up to the area the robot reports, within 5 %
PIXEL_AREA_M2 = 0.0025
BACKGROUND = (244, 247, 251)
WALL = (57, 72, 94)
FLOOR = (210, 216, 226)
ROOM_COLORS = [
    (151, 184, 238), (162, 213, 202), (225, 197, 151),
    (184, 177, 230), (236, 178, 189), (157, 205, 224),
]
ROUTE = (24, 132, 255)
DOCK = (46, 160, 67)


CMD_ROOM_CLEAN = 0x14
CMD_AREAS_SET, CMD_AREAS_REPORT = 0x1A, 0x1B
CMD_SPLIT, CMD_SPLIT_REPORT = 0x1C, 0x1D
CMD_MERGE, CMD_MERGE_REPORT = 0x1E, 0x1F
# no-go area modes of the Tuya laser protocol
AREA_MODES = {0: "all", 1: "no_sweep", 2: "no_mop"}
# the M5 Max ignores 0x12: barriers travel as two-point areas in 0x1a (tested 2026-10-28)
WALL_MODE = 0

type RawPoint = tuple[int, int]


def frame(payload: bytes) -> bytes:
    """Tuya laser sweeper frame, protocol version 0: aa 00 <len> <cmd + data> <sum>."""
    if len(payload) > 255:
        raise ValueError("command too long for a version 0 frame")
    return b"\xaa\x00" + bytes([len(payload)]) + payload + bytes([sum(payload) & 0xFF])


def encode(payload: bytes) -> str:
    return base64.b64encode(frame(payload)).decode()


def parse_frame(value: str | None) -> tuple[int, bytes] | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        data = base64.b64decode(value)
    except ValueError:
        return None
    if len(data) < 5 or data[0] != 0xAA:
        return None
    if data[1] == 0x01:
        length, start = int.from_bytes(data[2:6], "big"), 6
    else:
        length, start = data[2], 3
    body = data[start:start + length]
    if len(body) != length or not body:
        return None
    return body[0], body[1:]


def parse_base_state(value: str | None) -> bytes | None:
    """DP 158 of the base station: aa 00 07 01 <6 flag bytes> <sum>."""
    parsed = parse_frame(value)
    if parsed is None or parsed[0] != 0x01 or len(parsed[1]) <= max(BASE_FLAGS.values()):
        return None
    return parsed[1]


def room_clean_command(room_ids: list[int], repeats: int = 1) -> str:
    return encode(bytes([CMD_ROOM_CLEAN, repeats, len(room_ids), *room_ids]))


def _int16(raw: int) -> int:
    return raw - 0x10000 if raw >= 0x8000 else raw


def _point_bytes(point: RawPoint) -> bytes:
    return struct.pack(">HH", int(point[0]) & 0xFFFF, int(point[1]) & 0xFFFF)


def _points(data: bytes, count: int, pos: int) -> list[RawPoint]:
    return [
        (_int16(struct.unpack_from(">H", data, pos + 4 * i)[0]), _int16(struct.unpack_from(">H", data, pos + 4 * i + 2)[0]))
        for i in range(count)
    ]


def parse_areas(data: bytes) -> list[dict]:
    """0x1b data: count, then per area: mode, point count, points (int16 x, y)."""
    areas = []
    pos = 1
    for _ in range(data[0] if data else 0):
        mode, count = data[pos], data[pos + 1]
        areas.append({"mode": mode, "points": _points(data, count, pos + 2)})
        pos += 2 + 4 * count
    return areas


def areas_command(areas: list[dict]) -> str:
    body = bytes([CMD_AREAS_SET, len(areas)])
    for area in areas:
        body += bytes([area["mode"], len(area["points"])]) + b"".join(_point_bytes(p) for p in area["points"])
    return encode(body)


def zones_command(areas: list[dict], walls: list[list[RawPoint]]) -> str:
    """No-go areas and barriers in one 0x1a frame; raises ValueError when they do not fit."""
    return areas_command(areas + [{"mode": WALL_MODE, "points": wall} for wall in walls])


def split_zones(areas: list[dict]) -> tuple[list[dict], list[list[RawPoint]]]:
    return [a for a in areas if len(a["points"]) > 2], [a["points"] for a in areas if len(a["points"]) == 2]


def split_command(room_id: int, line: list[RawPoint]) -> str:
    return encode(bytes([CMD_SPLIT, room_id]) + b"".join(_point_bytes(p) for p in line))


def merge_command(room_ids: list[int]) -> str:
    return encode(bytes([CMD_MERGE, *room_ids]))


def parse_rooms(value: str | None) -> dict[int, str]:
    """DP 183: aa, 4 header bytes, 01, count, then per room: id 00 04 01 01 01 0f <type> <name_len> <name>."""
    if not value:
        return {}
    try:
        data = base64.b64decode(value)
    except ValueError:
        return {}
    if len(data) < 8 or data[0] != 0xAA:
        return {}
    rooms: dict[int, str] = {}
    pos = 7
    for _ in range(data[6]):
        if pos + 9 > len(data):
            break
        room_id, name_len = data[pos], data[pos + 8]
        rooms[room_id] = data[pos + 9:pos + 9 + name_len].decode(errors="replace")
        pos += 9 + name_len
    return rooms


def parse_mac(value: str | None) -> str | None:
    if not value:
        return None
    try:
        data = base64.b64decode(value)
    except ValueError:
        return None
    if len(data) != 11 or data[0] != 0xAA:
        return None
    return ":".join(f"{b:02x}" for b in data[4:10])


def active_faults(value: int | None) -> list[str]:
    if not value:
        return []
    return [FAULTS[bit] if bit < len(FAULTS) else f"fault_{bit}" for bit in range(30) if value >> bit & 1]


@dataclass
class RecordInfo:
    """Fields of the `extend` string of a cleaning record."""

    minutes: int
    area: int
    sections: list[int]


def parse_extend(extend: str) -> RecordInfo | None:
    parts = extend.split("_")
    if len(parts) < 9 or not all(p.isdigit() for p in parts[3:9]):
        return None
    return RecordInfo(int(parts[3]), int(parts[4]), [int(p) for p in parts[5:9]])


@dataclass
class CleaningMap:
    width: int
    height: int
    origin: tuple[int, int]
    pixels: bytes
    route: list[tuple[int, int]] = field(default_factory=list)
    cleaned_rooms: list[int] = field(default_factory=list)


def _lz4_block(src: bytes, size: int) -> bytes:
    out = bytearray()
    i = 0
    while i < len(src) and len(out) < size:
        token = src[i]
        i += 1
        length = token >> 4
        if length == 15:
            while True:
                b = src[i]
                i += 1
                length += b
                if b != 255:
                    break
        out += src[i:i + length]
        i += length
        if i >= len(src) or len(out) >= size:
            break
        offset = src[i] | src[i + 1] << 8
        i += 2
        if not 0 < offset <= len(out):
            raise ValueError("invalid LZ4 offset")
        length = (token & 15) + 4
        if token & 15 == 15:
            while True:
                b = src[i]
                i += 1
                length += b
                if b != 255:
                    break
        for _ in range(length):
            out.append(out[-offset])
    if len(out) < size:
        raise ValueError("truncated map")
    return bytes(out[:size])


def decode_record(data: bytes, sections: list[int]) -> CleaningMap:
    """app_map file: [map: 24-byte header + LZ4 pixels + room table][route][no-go zones][cleaned rooms frame]."""
    if len(data) < 24:
        raise ValueError("map file too short")
    width, height, ox, oy = struct.unpack_from(">HHHH", data, 4)
    if not (0 < width <= 2048 and 0 < height <= 2048):
        raise ValueError(f"invalid map size {width}x{height}")
    pixels = _lz4_block(data[24:sections[0] if sections else len(data)], width * height)
    result = CleaningMap(width, height, (ox, oy), pixels)
    if len(sections) >= 2:
        start, size = sections[0], sections[1]
        route = data[start:start + size]
        if len(route) >= 13:
            count = min(struct.unpack_from(">H", route, 7)[0], (len(route) - 13) // 4)
            points = [struct.unpack_from(">hh", route, 13 + 4 * k) for k in range(count)]
            while points and points[-1] == (0, 0):
                points.pop()
            result.route = points
    if len(sections) >= 4:
        start = sum(sections[:3])
        rooms = data[start:start + sections[3]]
        # aa, length, 0x15, repeats, count, ids..., checksum
        if len(rooms) >= 6 and rooms[0] == 0xAA and rooms[3] == 0x15:
            result.cleaned_rooms = list(rooms[6:6 + rooms[5]])
    return result


def _pixel_class(value: int) -> int:
    """-1 unknown, 0 floor without room, 1 wall, else room id + 2."""
    if value == MAP_UNKNOWN:
        return -1
    if value >= 240 or value & 3:
        return 1
    if value == 0:
        return 0
    return value // 4 + 2


def map_geometry(cmap: CleaningMap) -> dict:
    """Vector layers for the dashboard card, in map pixels relative to the mapped area.

    Each layer is an SVG path of rectangles: runs of equal pixels in a row,
    merged with the identical runs of the rows below.
    """
    w = cmap.width
    classes = [_pixel_class(v) for v in cmap.pixels]
    known = [i for i, c in enumerate(classes) if c >= 0]
    if not known:
        return {}
    x0 = min(i % w for i in known)
    x1 = max(i % w for i in known)
    y0, y1 = known[0] // w, known[-1] // w

    rects: dict[int, list[tuple[int, int, int, int]]] = {}
    open_runs: dict[tuple[int, int, int], int] = {}
    for y in range(y0, y1 + 2):
        runs: set[tuple[int, int, int]] = set()
        if y <= y1:
            row = classes[y * w + x0:y * w + x1 + 1]
            start = 0
            for x in range(1, len(row) + 1):
                if x == len(row) or row[x] != row[start]:
                    if row[start] >= 0:
                        runs.add((row[start], start, x))
                    start = x
        for run in [r for r in open_runs if r not in runs]:
            cls, xs, xe = run
            first = open_runs.pop(run)
            rects.setdefault(cls, []).append((xs, first - y0, xe - xs, y - first))
        for run in runs:
            open_runs.setdefault(run, y)

    def path(items: list[tuple[int, int, int, int]]) -> str:
        return "".join(f"M{x} {y}h{rw}v{rh}h-{rw}z" for x, y, rw, rh in items)

    rooms = []
    for cls, items in sorted(rects.items()):
        if cls < 2:
            continue
        room_id = cls - 2
        pixels = [(i % w - x0, i // w - y0) for i in known if classes[i] == cls]
        cx = sum(p[0] for p in pixels) / len(pixels)
        cy = sum(p[1] for p in pixels) / len(pixels)
        # a concave room can have its centroid outside: use the nearest pixel of the room
        lx, ly = min(pixels, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)
        rooms.append({
            "id": room_id,
            "path": path(items),
            "label": [lx + 0.5, ly + 0.5],
            "area": round(len(pixels) * PIXEL_AREA_M2, 1),
        })

    ox, oy = cmap.origin
    route = []
    for x, y in cmap.route:
        point = (round((x + ox) / 10 - x0, 1), round((oy - y) / 10 - y0, 1))
        if not route or route[-1] != point:
            route.append(point)
    return {
        "offset": [x0, y0],
        "origin": [ox, oy],
        "width": x1 - x0 + 1,
        "height": y1 - y0 + 1,
        "floor": path(rects.get(0, [])),
        "walls": path(rects.get(1, [])),
        "rooms": rooms,
        "route": "M" + "L".join(f"{x} {y}" for x, y in route) if len(route) > 1 else "",
        "dock": [ox / 10 - x0, oy / 10 - y0],
        "cleaned_rooms": cmap.cleaned_rooms,
    }


def merge_pixels(cmap: CleaningMap, old_ids: set[int], new_id: int) -> CleaningMap:
    """Preview of a merge until the next cleaning record brings the robot's own map."""
    pixels = bytes(
        new_id * 4 | v & 3 if v < 240 and v // 4 in old_ids else v for v in cmap.pixels
    )
    return replace(cmap, pixels=pixels)


def split_pixels(
    cmap: CleaningMap, room_id: int, new_id: int, line: tuple[tuple[float, float], tuple[float, float]]
) -> CleaningMap:
    """Preview of a split: the smaller side of the line, in map pixels, gets the new id."""
    (ax, ay), (bx, by) = line
    w = cmap.width
    sides: dict[bool, list[int]] = {True: [], False: []}
    for i, v in enumerate(cmap.pixels):
        if v < 240 and v // 4 == room_id and v:
            x, y = i % w, i // w
            sides[(bx - ax) * (y - ay) - (by - ay) * (x - ax) > 0].append(i)
    moved = set(min(sides.values(), key=len))
    pixels = bytes(new_id * 4 | v & 3 if i in moved else v for i, v in enumerate(cmap.pixels))
    return replace(cmap, pixels=pixels)


def render_map(cmap: CleaningMap, room_names: dict[int, str], scale: int = 2) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    palette = []
    for value in range(256):
        if value == MAP_UNKNOWN:
            color = BACKGROUND
        elif value >= 240 or value & 3:
            color = WALL
        elif value == 0:
            color = FLOOR
        else:
            color = ROOM_COLORS[(value // 4) % len(ROOM_COLORS)]
        palette.extend(color)
    img = Image.frombytes("P", (cmap.width, cmap.height), cmap.pixels)
    img.putpalette(palette)

    sums: dict[int, list[int]] = {}
    min_x, min_y, max_x, max_y = cmap.width, cmap.height, -1, -1
    for idx, value in enumerate(cmap.pixels):
        if value == MAP_UNKNOWN:
            continue
        x, y = idx % cmap.width, idx // cmap.width
        min_x, min_y = min(min_x, x), min(min_y, y)
        max_x, max_y = max(max_x, x), max(max_y, y)
        if 0 < value < 240 and not value & 3:
            acc = sums.setdefault(value // 4, [0, 0, 0])
            acc[0] += x
            acc[1] += y
            acc[2] += 1

    img = img.convert("RGB").resize((cmap.width * scale, cmap.height * scale), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(img)
    ox, oy = cmap.origin

    def to_px(x: int, y: int) -> tuple[float, float]:
        return (x + ox) / 10 * scale, (oy - y) / 10 * scale

    if len(cmap.route) > 1:
        draw.line([to_px(x, y) for x, y in cmap.route], fill=ROUTE, width=2, joint="curve")
    dx, dy = to_px(0, 0)
    draw.ellipse((dx - 6, dy - 6, dx + 6, dy + 6), fill=DOCK, outline=(255, 255, 255), width=2)
    font = ImageFont.load_default(size=7 * scale)
    for room_id, (sx, sy, n) in sums.items():
        label = room_names.get(room_id) or f"Room {room_id}"
        draw.text(
            (sx / n * scale, sy / n * scale), label, fill=(20, 20, 20), font=font,
            anchor="mm", stroke_width=2, stroke_fill=(255, 255, 255),
        )
    if max_x >= 0:
        pad = 10 * scale
        img = img.crop((
            max(0, min_x * scale - pad), max(0, min_y * scale - pad),
            min(img.width, (max_x + 1) * scale + pad), min(img.height, (max_y + 1) * scale + pad),
        ))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()

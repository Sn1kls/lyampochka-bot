"""Reads the outage grid out of a Volynoblenergo schedule PNG with stdlib only."""

import struct
import zlib

from poweron.core.ports import ApiSchemaError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_SIDE = 4000
ON = (185, 200, 215)
OFF = (68, 110, 155)
COLUMNS = 24
ROWS_PER_HALF = 12
MIN_RUN = 20
HALF_GAP = 100
SUBQUEUES = tuple(f"{queue}.{part}" for queue in range(1, 7) for part in (1, 2))

Rows = list[bytearray]


def decode_schedule(content: bytes) -> dict[str, str]:
    """Subqueue -> 48 raw slot codes ("0" = power on, "1" = off) from 00:00 in half-hour steps."""
    # ponytail: ~1-2 s of pure Python per image (run it off the event loop); Pillow if it ever matters.
    rows, bytes_per_pixel = _read_png(content)
    columns = _column_centres(rows, bytes_per_pixel)
    row_centres = _row_centres(rows, bytes_per_pixel, columns[0])
    grid: dict[str, list[str]] = {subqueue: [] for subqueue in SUBQUEUES}
    for half in (row_centres[:ROWS_PER_HALF], row_centres[ROWS_PER_HALF:]):
        for subqueue, row in zip(SUBQUEUES, half, strict=True):
            grid[subqueue] += [_slot(rows[row], column * bytes_per_pixel) for column in columns]
    return {subqueue: "".join(slots) for subqueue, slots in grid.items()}


def _slot(row: bytearray, offset: int) -> str:
    colour = tuple(row[offset : offset + 3])
    if colour == ON:
        return "0"
    if colour == OFF:
        return "1"
    raise ApiSchemaError(f"schedule image: unexpected cell colour {colour}")


def _centres(line: list[tuple[int, ...]]) -> list[int]:
    """Centres of the ON/OFF coloured stretches longer than MIN_RUN pixels."""
    centres = []
    start = 0
    for position in range(1, len(line) + 1):
        if position == len(line) or line[position] != line[start]:
            if line[start] in (ON, OFF) and position - start > MIN_RUN:
                centres.append((start + position - 1) // 2)
            start = position
    return centres


def _column_centres(rows: Rows, bytes_per_pixel: int) -> list[int]:
    """The first pixel row ending in 24 evenly spaced coloured stretches is the time header."""
    for row in rows:
        pixels = [tuple(row[offset : offset + 3]) for offset in range(0, len(row), bytes_per_pixel)]
        centres = _centres(pixels)
        if len(centres) >= COLUMNS and _evenly_spaced(centres[-COLUMNS:]):
            return centres[-COLUMNS:]
    raise ApiSchemaError("schedule image: no time header found")


def _evenly_spaced(centres: list[int]) -> bool:
    pitches = {after - before for before, after in zip(centres, centres[1:], strict=False)}
    return max(pitches) - min(pitches) <= 2 and min(pitches) > MIN_RUN


def _row_centres(rows: Rows, bytes_per_pixel: int, column: int) -> list[int]:
    offset = column * bytes_per_pixel
    centres = _centres([tuple(row[offset : offset + 3]) for row in rows])
    halves: list[list[int]] = [[]]
    for centre in centres:
        if halves[-1] and centre - halves[-1][-1] > HALF_GAP:
            halves.append([])
        halves[-1].append(centre)
    if len(halves) != 2 or any(len(half) != ROWS_PER_HALF + 1 for half in halves):
        raise ApiSchemaError("schedule image: unexpected row layout")
    return halves[0][1:] + halves[1][1:]  # the first stretch of each half is the time header


def _read_png(content: bytes) -> tuple[Rows, int]:
    if not content.startswith(PNG_SIGNATURE):
        raise ApiSchemaError("schedule image: not a PNG")
    header = None
    compressed = bytearray()
    position = len(PNG_SIGNATURE)
    while position + 8 <= len(content):
        length, kind = struct.unpack(">I4s", content[position : position + 8])
        body = content[position + 8 : position + 8 + length]
        if len(body) != length:
            raise ApiSchemaError("schedule image: truncated PNG")
        if kind == b"IHDR" and length == 13:
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            compressed += body
        elif kind == b"IEND":
            break
        position += 12 + length
    if header is None:
        raise ApiSchemaError("schedule image: no IHDR")
    width, height, depth, colour_type, _, _, interlace = header
    if (
        depth != 8
        or colour_type not in (2, 6)
        or interlace
        or not 0 < width <= MAX_SIDE
        or not 0 < height <= MAX_SIDE
    ):
        raise ApiSchemaError(f"schedule image: unsupported PNG {header}")
    bytes_per_pixel = 3 if colour_type == 2 else 4
    stride = width * bytes_per_pixel
    expected = height * (stride + 1)
    try:
        raw = zlib.decompressobj().decompress(bytes(compressed), expected + 1)
    except zlib.error as error:
        raise ApiSchemaError("schedule image: bad zlib data") from error
    if len(raw) != expected:
        raise ApiSchemaError("schedule image: unexpected decompressed size")
    return _unfilter(raw, height, stride, bytes_per_pixel), bytes_per_pixel


def _unfilter(raw: bytes, height: int, stride: int, bytes_per_pixel: int) -> Rows:
    rows: Rows = []
    previous = bytearray(stride)
    for index in range(height):
        start = index * (stride + 1)
        filter_type = raw[start]
        row = bytearray(raw[start + 1 : start + 1 + stride])
        if filter_type == 1:
            for position in range(bytes_per_pixel, stride):
                row[position] = (row[position] + row[position - bytes_per_pixel]) & 255
        elif filter_type == 2:
            row = bytearray((cur + up) & 255 for cur, up in zip(row, previous, strict=True))
        elif filter_type == 3:
            for position in range(stride):
                left = row[position - bytes_per_pixel] if position >= bytes_per_pixel else 0
                row[position] = (row[position] + ((left + previous[position]) >> 1)) & 255
        elif filter_type == 4:
            for position in range(stride):
                left = corner = 0
                if position >= bytes_per_pixel:
                    left = row[position - bytes_per_pixel]
                    corner = previous[position - bytes_per_pixel]
                up = previous[position]
                estimate = left + up - corner
                distance_left = abs(estimate - left)
                distance_up = abs(estimate - up)
                distance_corner = abs(estimate - corner)
                if distance_left <= distance_up and distance_left <= distance_corner:
                    predictor = left
                elif distance_up <= distance_corner:
                    predictor = up
                else:
                    predictor = corner
                row[position] = (row[position] + predictor) & 255
        elif filter_type != 0:
            raise ApiSchemaError(f"schedule image: bad PNG filter {filter_type}")
        rows.append(row)
        previous = row
    return rows

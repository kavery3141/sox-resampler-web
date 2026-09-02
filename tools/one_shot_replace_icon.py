from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

OUT_SIZE = 1024
SCALE = 2
SIZE = OUT_SIZE * SCALE
CYAN = (24, 182, 236, 255)
DARK = (11, 21, 30, 255)

buf = bytearray(SIZE * SIZE * 4)


def set_px(x: int, y: int, color: tuple[int, int, int, int]) -> None:
    if 0 <= x < SIZE and 0 <= y < SIZE:
        i = (y * SIZE + x) * 4
        buf[i:i + 4] = bytes(color)


def fill_circle(cx: float, cy: float, radius: float, color: tuple[int, int, int, int]) -> None:
    cx *= SCALE
    cy *= SCALE
    radius *= SCALE
    x0 = max(0, int(cx - radius))
    x1 = min(SIZE - 1, int(cx + radius))
    y0 = max(0, int(cy - radius))
    y1 = min(SIZE - 1, int(cy + radius))
    rr = radius * radius
    pixel = bytes(color)
    for y in range(y0, y1 + 1):
        dy = y + 0.5 - cy
        span2 = rr - dy * dy
        if span2 < 0:
            continue
        span = math.sqrt(span2)
        xa = max(x0, int(math.ceil(cx - span - 0.5)))
        xb = min(x1, int(math.floor(cx + span - 0.5)))
        if xa > xb:
            continue
        row = (y * SIZE + xa) * 4
        buf[row:row + (xb - xa + 1) * 4] = pixel * (xb - xa + 1)


def cubic(p0, p1, p2, p3, t: float) -> tuple[float, float]:
    u = 1.0 - t
    return (
        u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
        u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1],
    )


def stroke_cubic(p0, p1, p2, p3, width: float, color, steps: int = 340) -> None:
    radius = width / 2.0
    for i in range(steps + 1):
        fill_circle(*cubic(p0, p1, p2, p3, i / steps), radius, color)


def edge(a, b, p) -> float:
    return (p[0] - a[0]) * (b[1] - a[1]) - (p[1] - a[1]) * (b[0] - a[0])


def fill_triangle(a, b, c, color) -> None:
    pts = [(v[0] * SCALE, v[1] * SCALE) for v in (a, b, c)]
    minx = max(0, int(min(p[0] for p in pts)))
    maxx = min(SIZE - 1, int(max(p[0] for p in pts)))
    miny = max(0, int(min(p[1] for p in pts)))
    maxy = min(SIZE - 1, int(max(p[1] for p in pts)))
    aa, bb, cc = pts
    area = edge(aa, bb, cc)
    for y in range(miny, maxy + 1):
        py = y + 0.5
        for x in range(minx, maxx + 1):
            p = (x + 0.5, py)
            e1, e2, e3 = edge(aa, bb, p), edge(bb, cc, p), edge(cc, aa, p)
            if (area >= 0 and e1 >= 0 and e2 >= 0 and e3 >= 0) or (
                area < 0 and e1 <= 0 and e2 <= 0 and e3 <= 0
            ):
                set_px(x, y, color)


# Transparent corners, near-black circular field, cyan opposing resampler arrows.
fill_circle(512, 512, 438, DARK)

# Lower-left arrow first so the upper arrow reads naturally at the crossing.
stroke_cubic((790, 755), (690, 730), (655, 605), (565, 555), 66, CYAN)
stroke_cubic((565, 555), (475, 505), (410, 570), (340, 690), 66, CYAN)
stroke_cubic((340, 690), (330, 710), (318, 724), (304, 733), 66, CYAN, steps=80)
fill_triangle((206, 830), (353, 748), (280, 675), CYAN)

# Upper-right arrow.
stroke_cubic((235, 475), (320, 390), (380, 610), (490, 600), 66, CYAN)
stroke_cubic((490, 600), (610, 590), (625, 430), (705, 330), 66, CYAN)
stroke_cubic((705, 330), (720, 312), (735, 300), (747, 294), 66, CYAN, steps=80)
fill_triangle((822, 195), (680, 255), (760, 345), CYAN)

# 2x box downsample for clean antialiased edges.
small = bytearray(OUT_SIZE * OUT_SIZE * 4)
for y in range(OUT_SIZE):
    for x in range(OUT_SIZE):
        sums = [0, 0, 0, 0]
        for oy in (0, 1):
            for ox in (0, 1):
                i = (((y * SCALE + oy) * SIZE) + (x * SCALE + ox)) * 4
                for channel in range(4):
                    sums[channel] += buf[i + channel]
        j = (y * OUT_SIZE + x) * 4
        small[j:j + 4] = bytes(value // 4 for value in sums)


def chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


raw = bytearray()
stride = OUT_SIZE * 4
for y in range(OUT_SIZE):
    raw.append(0)
    start = y * stride
    raw.extend(small[start:start + stride])

png = b"\x89PNG\r\n\x1a\n"
png += chunk(b"IHDR", struct.pack(">IIBBBBB", OUT_SIZE, OUT_SIZE, 8, 6, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
png += chunk(b"IEND", b"")

for target in (Path("assets/icon.png"), Path("app/static/icon.png")):
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(png)

print(f"Wrote {len(png)} byte 1024x1024 RGBA PNG to both icon paths.")

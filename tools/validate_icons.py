from __future__ import annotations

import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MIN_SIZE = 128
ICON_PATHS = (Path("assets/icon.png"), Path("app/static/icon.png"))


def validate_png(path: Path) -> bytes:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        raise SystemExit(f"{path}: invalid PNG signature")

    pos = len(PNG_SIGNATURE)
    width = height = None
    idat = bytearray()
    saw_iend = False

    while pos < len(data):
        if pos + 12 > len(data):
            raise SystemExit(f"{path}: truncated PNG chunk header")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        payload_start = pos + 8
        payload_end = payload_start + length
        crc_end = payload_end + 4
        if crc_end > len(data):
            raise SystemExit(f"{path}: truncated PNG chunk {kind!r}")

        payload = data[payload_start:payload_end]
        stored_crc = struct.unpack(">I", data[payload_end:crc_end])[0]
        actual_crc = zlib.crc32(kind)
        actual_crc = zlib.crc32(payload, actual_crc) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise SystemExit(f"{path}: invalid CRC for PNG chunk {kind!r}")

        if kind == b"IHDR":
            if length != 13:
                raise SystemExit(f"{path}: invalid IHDR length")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
            if bit_depth != 8 or color_type != 6:
                raise SystemExit(f"{path}: expected 8-bit RGBA PNG")
            if compression != 0 or filtering != 0 or interlace != 0:
                raise SystemExit(f"{path}: unsupported PNG encoding")
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            saw_iend = True
            break

        pos = crc_end

    if width is None or height is None or width != height or width < MIN_SIZE:
        raise SystemExit(
            f"{path}: expected a square PNG at least {MIN_SIZE}x{MIN_SIZE}, got {width}x{height}"
        )
    if not idat or not saw_iend:
        raise SystemExit(f"{path}: PNG is missing IDAT or IEND")

    try:
        zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise SystemExit(f"{path}: corrupt compressed PNG image data: {exc}") from exc

    return data


def main() -> None:
    first = validate_png(ICON_PATHS[0])
    second = validate_png(ICON_PATHS[1])
    if first != second:
        raise SystemExit("assets/icon.png and app/static/icon.png are not identical")
    print("App icons are identical, structurally valid square RGBA PNG files.")


if __name__ == "__main__":
    main()

"""Pack web/icons/icon-{16..256}.png into a multi-size Windows icon (web/icons/hive.ico). Stdlib only.

PNGs are rendered from web/icons/hive.svg (see README "Logo"). ICO entries may embed PNG data directly.
"""
import struct
from pathlib import Path

ICONS = Path(__file__).resolve().parent.parent / "web" / "icons"
SIZES = [16, 32, 48, 256]


def main() -> None:
    blobs = [(s, (ICONS / f"icon-{s}.png").read_bytes()) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, data = b"", b""
    for size, png in blobs:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    (ICONS / "hive.ico").write_bytes(header + entries + data)
    print(f"wrote {ICONS / 'hive.ico'} ({len(header + entries + data)} bytes, sizes {SIZES})")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Publish a Board firmware build so Stickies on this server offer it as an over-the-air update.

    uv run python scripts/publish_firmware.py ~/projects/sticky-firmware/.pio/build/sticky_board

Copies firmware.bin to $STICKY_DATA_DIR/firmware/sticky-<version>.bin and writes sticky.json
({version, file, size, sha256}). The version comes from sticky_version.txt, which the firmware's
build script writes next to the binary. Keeps the three newest images.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from sticky_server import config  # noqa: E402

KEEP = 3


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build = Path(sys.argv[1]).expanduser()
    binary = build / "firmware.bin"
    version = (build / "sticky_version.txt").read_text().strip()
    if not binary.is_file():
        sys.exit(f"missing {binary}")
    out = config.load().firmware_dir
    name = f"sticky-{version}.bin"
    shutil.copy2(binary, out / name)
    data = (out / name).read_bytes()
    manifest = {"version": version, "file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    tmp = out / "sticky.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1) + "\n")
    tmp.replace(out / "sticky.json")
    for old in sorted(out.glob("sticky-*.bin"), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]:
        old.unlink()
    print(f"published {name} ({len(data) // 1024} KB) to {out}")


if __name__ == "__main__":
    main()

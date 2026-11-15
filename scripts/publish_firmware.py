#!/usr/bin/env python3
"""Publish a Board firmware build so Stickies on this server offer it as an over-the-air update.

    uv run python scripts/publish_firmware.py ~/projects/sticky-firmware/.pio/build/sticky_board
    uv run python scripts/publish_firmware.py firmware/.pio/build/sticky --channel sticky-os   # our own firmware

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
    args = sys.argv[1:]
    channel = "sticky"
    if "--channel" in args:
        i = args.index("--channel")
        channel = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit(__doc__)
    build = Path(args[0]).expanduser()
    binary = build / "firmware.bin"
    version = (build / "sticky_version.txt").read_text().strip()
    if not binary.is_file():
        sys.exit(f"missing {binary}")
    out = config.load().firmware_dir
    name = f"{channel}-{version}.bin" if channel != "sticky" else f"sticky-{version}.bin"
    shutil.copy2(binary, out / name)
    data = (out / name).read_bytes()
    manifest = {"version": version, "file": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    tmp = out / f"{channel}.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1) + "\n")
    tmp.replace(out / f"{channel}.json")
    pattern = f"{channel}-*.bin" if channel != "sticky" else "sticky-[0-9a-f]*.bin"
    for old in sorted(out.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)[KEEP:]:
        old.unlink()
    print(f"published {name} ({len(data) // 1024} KB) to {out}")


if __name__ == "__main__":
    main()

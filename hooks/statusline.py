#!/usr/bin/env python3
"""Claude Code status line: prints a short line and reports rate limits to the Sticky server.

Posts at most once a minute per machine, in a detached child, so the status line stays instant.
Config: ~/.config/sticky/client.env with STICKY_URL and STICKY_TOKEN.
"""

import json
import os
import socket
import sys
import time
import urllib.request
from pathlib import Path


def load_conf() -> dict:
    conf = {}
    path = Path(os.environ.get("STICKY_CLIENT_ENV", Path.home() / ".config/sticky/client.env"))
    if path.is_file():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, _, v = line.partition("=")
                conf[k.strip()] = v.strip().strip('"').strip("'")
    return conf


def report(data: dict, conf: dict) -> None:
    stamp = Path.home() / ".cache/sticky-statusline.stamp"
    try:
        if time.time() - stamp.stat().st_mtime < 60:
            return
    except FileNotFoundError:
        pass
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.touch()
    if os.fork() != 0:
        return
    try:
        os.setsid()
        body = {
            "sticky_host": socket.gethostname().split(".")[0],
            "rate_limits": data.get("rate_limits"),
            "model": data.get("model"),
        }
        req = urllib.request.Request(
            conf["STICKY_URL"] + "/api/statusline",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Sticky-Token": conf.get("STICKY_TOKEN", "")},
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass
    os._exit(0)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    conf = load_conf()
    if conf.get("STICKY_URL") and data.get("rate_limits"):
        report(data, conf)

    parts = [(data.get("model") or {}).get("display_name", "Claude")]
    ctx = (data.get("context_window") or {}).get("used_percentage")
    if ctx is not None:
        parts.append(f"ctx {ctx:.0f}%")
    five = ((data.get("rate_limits") or {}).get("five_hour") or {}).get("used_percentage")
    if five is not None:
        parts.append(f"5h {five:.0f}%")
    cwd = (data.get("workspace") or {}).get("current_dir") or data.get("cwd")
    if cwd:
        parts.append(Path(cwd).name)
    print("  ".join(parts))


if __name__ == "__main__":
    main()

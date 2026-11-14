"""Run on a second machine (cron) to send its Claude Code usage to the Sticky server.

    uv run python -m sticky_server.push           # reads ~/.config/sticky/client.env
"""

from __future__ import annotations

import json
import os
import socket
import urllib.request
from pathlib import Path

from . import config
from .usage import collect_local


def main() -> None:
    conf_path = Path(os.environ.get("STICKY_CLIENT_ENV", Path.home() / ".config/sticky/client.env"))
    conf = dict(
        line.split("=", 1) for line in conf_path.read_text().splitlines() if "=" in line and not line.startswith("#")
    )
    url, token = conf["STICKY_URL"].strip(), conf.get("STICKY_TOKEN", "").strip()
    host = socket.gethostname().split(".")[0]
    payload = collect_local(config.load(), {})
    req = urllib.request.Request(
        f"{url}/api/usage/push?host={host}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Sticky-Token": token},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        print(resp.status, resp.read().decode())


if __name__ == "__main__":
    main()

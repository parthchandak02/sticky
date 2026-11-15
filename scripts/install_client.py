#!/usr/bin/env python3
"""Point this machine's Claude Code at a Sticky server.

    python3 scripts/install_client.py --url http://my-server.local:8787 --token XXX
    python3 scripts/install_client.py --url ... --token XXX --approve 45   # answer prompts on the Sticky
    python3 scripts/install_client.py --uninstall

Writes ~/.config/sticky/client.env, then adds hook entries (and a status line, only if you
have none) to ~/.claude/settings.json. Existing hooks are kept. A backup is written first.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HOOK = REPO / "hooks" / "sticky-hook.sh"
APPROVE_HOOK = REPO / "hooks" / "sticky-permission.py"
STATUSLINE = REPO / "hooks" / "statusline.py"
SETTINGS = Path.home() / ".claude" / "settings.json"
CLIENT_ENV = Path.home() / ".config" / "sticky" / "client.env"
EVENTS = ["SessionStart", "UserPromptSubmit", "Notification", "PermissionRequest", "Stop", "SessionEnd"]
MARKS = ("sticky-hook.sh", "sticky-permission.py")


def strip_ours(settings: dict) -> None:
    hooks = settings.get("hooks", {})
    for event in list(hooks):
        groups = []
        for group in hooks[event]:
            group["hooks"] = [h for h in group.get("hooks", []) if not any(m in h.get("command", "") for m in MARKS)]
            if group["hooks"]:
                groups.append(group)
        if groups:
            hooks[event] = groups
        else:
            del hooks[event]
    if not hooks:
        settings.pop("hooks", None)
    if "statusline.py" in (settings.get("statusLine") or {}).get("command", "") and str(REPO) in settings[
        "statusLine"
    ].get("command", ""):
        del settings["statusLine"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--token", default="")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--no-statusline", action="store_true")
    ap.add_argument("--approve", type=int, default=0, metavar="SECONDS",
                    help="let the Sticky answer permission prompts; the terminal asks after SECONDS")
    args = ap.parse_args()

    settings = json.loads(SETTINGS.read_text()) if SETTINGS.is_file() else {}
    if SETTINGS.is_file():
        backup = SETTINGS.with_name(f"settings.json.bak-sticky-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(SETTINGS, backup)
        print(f"backup: {backup}")
    strip_ours(settings)

    if args.uninstall:
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
        print("removed Sticky hooks and status line")
        return
    if not args.url:
        ap.error("--url is required")

    CLIENT_ENV.parent.mkdir(parents=True, exist_ok=True)
    env = f"STICKY_URL={args.url.rstrip('/')}\nSTICKY_TOKEN={args.token}\n"
    if args.approve:
        env += f"STICKY_APPROVE_WAIT={args.approve}\n"
    CLIENT_ENV.write_text(env)
    CLIENT_ENV.chmod(0o600)
    print(f"wrote {CLIENT_ENV}")

    hooks = settings.setdefault("hooks", {})
    for event in EVENTS:
        hooks.setdefault(event, []).append(
            {"hooks": [{"type": "command", "command": f"sh '{HOOK}'", "timeout": 5}]}
        )
    if args.approve:
        hooks.setdefault("PermissionRequest", []).append(
            {"hooks": [{"type": "command", "command": f"python3 '{APPROVE_HOOK}'", "timeout": args.approve + 15}]}
        )
        print(f"permission prompts wait {args.approve}s for the Sticky, then ask in the terminal")
    if args.no_statusline:
        pass
    elif "statusLine" in settings:
        print("kept your existing statusLine; rate limits will not reach the board (see README)")
    else:
        settings["statusLine"] = {"type": "command", "command": f"python3 '{STATUSLINE}'"}
        print("added status line")
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"added hooks for: {', '.join(EVENTS)}")


if __name__ == "__main__":
    main()

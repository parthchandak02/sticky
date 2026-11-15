#!/usr/bin/env python3
"""Claude Code PermissionRequest hook: let the Sticky answer a permission prompt.

Posts the prompt to the Sticky server, then waits up to STICKY_APPROVE_WAIT seconds (server
default 45) for a hold-to-allow or a deny on the device. If nobody answers, it prints nothing
and Claude Code shows its normal prompt in the terminal. Any error does the same: this hook
never allows anything on its own.

Sent to the server: the tool name, the working directory, and a one-line summary of what the
tool wants to do (the Bash command, or the file path for edits), cut to 300 characters.
Config: ~/.config/sticky/client.env with STICKY_URL, STICKY_TOKEN, optional STICKY_APPROVE_WAIT.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> dict[str, str]:
    env = dict(os.environ)
    conf = Path(env.get("STICKY_CLIENT_ENV", Path.home() / ".config/sticky/client.env"))
    if conf.is_file():
        for line in conf.read_text().splitlines():
            key, _, value = line.strip().partition("=")
            if key and not key.startswith("#") and key not in env:
                env[key] = value.strip().strip("'\"")
    return env


def summary(tool: str, tool_input: dict) -> str:
    if tool == "Bash":
        return str(tool_input.get("command", ""))
    for key in ("file_path", "path", "url", "pattern"):
        if tool_input.get(key):
            return str(tool_input[key])
    return tool


def call(env: dict[str, str], method: str, path: str, body: dict | None = None, timeout: float = 5) -> dict:
    req = urllib.request.Request(env["STICKY_URL"].rstrip("/") + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json",
                                          "X-Sticky-Token": env.get("STICKY_TOKEN", "")})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def main() -> None:
    env = load_env()
    if env.get("STICKY_HOOK_DISABLE") == "1" or not env.get("STICKY_URL"):
        return
    try:
        event = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    tool = event.get("tool_name", "")
    payload = {"session_id": event.get("session_id", ""), "cwd": event.get("cwd", ""), "tool_name": tool,
               "summary": summary(tool, event.get("tool_input") or {})[:300],
               "sticky_host": socket.gethostname().split(".")[0]}
    try:
        opened = call(env, "POST", "/api/permission", payload)
        pid = opened["id"]
        wait = float(env.get("STICKY_APPROVE_WAIT") or opened.get("wait", 45))
        deadline = time.time() + wait
        decision = None
        while decision is None and time.time() < deadline:
            left = min(25.0, deadline - time.time())
            decision = call(env, "GET", f"/api/permission/{pid}?wait={left:.0f}", timeout=left + 5).get("decision")
        if decision not in ("allow", "deny"):
            call(env, "POST", f"/api/permission/{pid}/expire")
            return  # no answer: the terminal asks as usual
    except (urllib.error.URLError, OSError, KeyError, ValueError):
        return
    out = {"behavior": decision}
    if decision == "deny":
        out["message"] = "Denied from the Sticky."
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": out}}))


if __name__ == "__main__":
    main()

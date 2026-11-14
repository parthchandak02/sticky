"""Live state pushed by Claude Code hooks and the status line, persisted as one JSON file."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

# Hook event -> session state shown on the board.
EVENT_STATE = {
    "SessionStart": "idle",
    "UserPromptSubmit": "working",
    "PreToolUse": "working",
    "PostToolUse": "working",
    "SubagentStop": "working",
    "Stop": "idle",
    "SessionEnd": "ended",
}
WAITING_NOTIFICATIONS = {"permission_prompt", "elicitation_dialog", "agent_needs_input"}

ENDED_TTL = 10 * 60
IDLE_TTL = 6 * 3600
ANY_TTL = 24 * 3600


class State:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"sessions": {}, "limits": {}, "usage_pushes": {}, "devices": {}}
        if path.is_file():
            try:
                self.data.update(json.loads(path.read_text()))
            except json.JSONDecodeError:
                pass

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        tmp.replace(self.path)

    # ---- hooks -------------------------------------------------------------
    def apply_hook(self, event: dict[str, Any], now: float | None = None) -> dict[str, Any] | None:
        now = now or time.time()
        name = event.get("hook_event_name", "")
        sid = event.get("session_id")
        if not sid:
            return None
        host = event.get("sticky_host") or "unknown"
        key = f"{host}:{sid}"
        with self._lock:
            sess = self.data["sessions"].setdefault(
                key, {"host": host, "session_id": sid, "started_at": now, "state": "idle"}
            )
            cwd = event.get("cwd") or sess.get("cwd") or ""
            sess["cwd"] = cwd
            sess["project"] = Path(cwd).name if cwd else sess.get("project", "?")
            sess["last_event"] = name
            sess["updated_at"] = now
            if name == "Notification":
                ntype = event.get("notification_type", "")
                msg = event.get("message", "")
                if ntype in WAITING_NOTIFICATIONS or "permission" in msg.lower():
                    sess["state"] = "waiting"
                    sess["message"] = msg[:200]
                elif ntype == "idle_prompt":
                    sess["state"] = "idle"
            elif name == "PermissionRequest":
                sess["state"] = "waiting"
                tool = event.get("tool_name", "")
                sess["message"] = f"Allow {tool}?" if tool else "Permission needed"
            elif name in EVENT_STATE:
                sess["state"] = EVENT_STATE[name]
                if name in ("UserPromptSubmit", "Stop", "SessionStart"):
                    sess.pop("message", None)
            self._prune(now)
            self._save()
            return dict(sess)

    def _prune(self, now: float) -> None:
        sessions = self.data["sessions"]
        for key in list(sessions):
            s = sessions[key]
            age = now - s.get("updated_at", 0)
            if (
                (s["state"] == "ended" and age > ENDED_TTL)
                or (s["state"] == "idle" and age > IDLE_TTL)
                or age > ANY_TTL
            ):
                del sessions[key]

    def sessions(self, now: float | None = None) -> list[dict[str, Any]]:
        now = now or time.time()
        with self._lock:
            self._prune(now)
            items = [dict(s) for s in self.data["sessions"].values() if s["state"] != "ended"]
        order = {"waiting": 0, "working": 1, "idle": 2}
        return sorted(items, key=lambda s: (order.get(s["state"], 3), -s.get("updated_at", 0)))

    # ---- status line rate limits -------------------------------------------
    def apply_statusline(self, payload: dict[str, Any], now: float | None = None) -> None:
        now = now or time.time()
        host = payload.get("sticky_host") or "unknown"
        limits = payload.get("rate_limits") or {}
        if not limits:
            return
        with self._lock:
            self.data["limits"][host] = {
                "five_hour": limits.get("five_hour"),
                "seven_day": limits.get("seven_day"),
                "model": (payload.get("model") or {}).get("display_name"),
                "updated_at": now,
            }
            self._save()

    def limits(self) -> dict[str, Any] | None:
        """Most recently reported limits across hosts (they share one account)."""
        with self._lock:
            reports = list(self.data["limits"].values())
        return max(reports, key=lambda r: r["updated_at"]) if reports else None

    # ---- usage pushed from other machines ----------------------------------
    def apply_usage_push(self, host: str, payload: dict[str, Any], now: float | None = None) -> None:
        with self._lock:
            self.data["usage_pushes"][host] = {"payload": payload, "updated_at": now or time.time()}
            self._save()

    def usage_pushes(self) -> dict[str, Any]:
        with self._lock:
            return {h: v["payload"] for h, v in self.data["usage_pushes"].items()}

    # ---- devices -------------------------------------------------------------
    def device_seen(self, address: str, firmware: str, page: str, now: float | None = None) -> None:
        with self._lock:
            devices = self.data.setdefault("devices", {})
            prev = devices.get(address, {})
            devices[address] = {"address": address, "firmware": firmware or prev.get("firmware", ""),
                                "page": page, "seen_at": now or time.time()}
            if prev.get("firmware") != devices[address]["firmware"]:
                self._save()  # persist version changes; plain check-ins stay in memory

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.data.get("devices", {}).values(), key=lambda d: -d["seen_at"])

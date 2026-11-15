"""Live state pushed by Claude Code hooks and the status line, persisted as one JSON file."""

from __future__ import annotations

import json
import secrets
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
        self._decided = threading.Condition(self._lock)
        self.data: dict[str, Any] = {"sessions": {}, "limits": {}, "usage_pushes": {}, "devices": {},
                                     "permissions": {}, "fridge": {}}
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
    def device_seen(self, address: str, firmware: str, page: str, now: float | None = None,
                    telemetry: dict[str, Any] | None = None) -> None:
        with self._lock:
            devices = self.data.setdefault("devices", {})
            prev = devices.get(address, {})
            devices[address] = {**prev, "address": address, "firmware": firmware or prev.get("firmware", ""),
                                "page": page, "seen_at": now or time.time(), **(telemetry or {})}
            if prev.get("firmware") != devices[address]["firmware"]:
                self._save()  # persist version changes; plain check-ins stay in memory

    def latest_device(self) -> dict[str, Any] | None:
        with self._lock:
            ds = list(self.data.get("devices", {}).values())
        return max(ds, key=lambda d: d["seen_at"]) if ds else None

    def devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self.data.get("devices", {}).values(), key=lambda d: -d["seen_at"])

    # ---- permission prompts answered on the device ----------------------------
    PERMISSION_TTL = 15 * 60

    def open_permission(self, event: dict[str, Any], now: float | None = None) -> str:
        """A PermissionRequest that the hook is waiting on. Returns its id."""
        now = now or time.time()
        host = event.get("sticky_host") or "unknown"
        pid = secrets.token_urlsafe(9)
        cwd = event.get("cwd") or ""
        with self._lock:
            perms = self.data.setdefault("permissions", {})
            for k in [k for k, p in perms.items() if now - p["created"] > self.PERMISSION_TTL]:
                del perms[k]
            perms[pid] = {"id": pid, "host": host, "session_id": event.get("session_id", ""),
                          "project": Path(cwd).name if cwd else "?", "cwd": cwd,
                          "tool": event.get("tool_name", ""), "summary": str(event.get("summary", ""))[:300],
                          "created": now, "decision": None}
            self._save()
        return pid

    def pending_permission(self, host: str, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            for p in self.data.get("permissions", {}).values():
                if p["decision"] is None and p["host"] == host and p["session_id"] == session_id:
                    return dict(p)
        return None

    def permission(self, pid: str) -> dict[str, Any] | None:
        with self._lock:
            p = self.data.get("permissions", {}).get(pid)
            return dict(p) if p else None

    def decide_permission(self, pid: str, decision: str, now: float | None = None) -> bool:
        """allow, deny, or expired (the hook gave up and the terminal asks instead)."""
        if decision not in ("allow", "deny", "expired"):
            raise ValueError(decision)
        with self._lock:
            p = self.data.get("permissions", {}).get(pid)
            if not p or p["decision"] is not None:
                return False
            p["decision"], p["decided_at"] = decision, now or time.time()
            key = f"{p['host']}:{p['session_id']}"
            sess = self.data["sessions"].get(key)
            if sess and decision in ("allow", "deny"):
                sess["state"] = "working" if decision == "allow" else "idle"
                sess["message"] = ("Allowed from the Sticky" if decision == "allow" else "You said no on the Sticky")
            self._save()
            self._decided.notify_all()
            return True

    def wait_permission(self, pid: str, timeout: float) -> dict[str, Any] | None:
        deadline = time.time() + timeout
        with self._decided:
            while True:
                p = self.data.get("permissions", {}).get(pid)
                if not p or p["decision"] is not None:
                    return dict(p) if p else None
                left = deadline - time.time()
                if left <= 0:
                    return dict(p)
                self._decided.wait(left)

    # ---- fridge: hearts, photo cursor, one-shot toasts ----------------------
    def fridge(self) -> dict[str, Any]:
        with self._lock:
            return dict(self.data.setdefault("fridge", {}))

    def fridge_update(self, **kw: Any) -> None:
        with self._lock:
            self.data.setdefault("fridge", {}).update(kw)
            self._save()

    def flash(self, text: str | None = None) -> str | None:
        """Set a toast (text) or take the pending one (no text)."""
        with self._lock:
            f = self.data.setdefault("fridge", {})
            if text is not None:
                f["toast"] = {"text": text, "at": time.time()}
                self._save()
                return text
            t = f.pop("toast", None)
            if t:
                self._save()
            return t["text"] if t and time.time() - t["at"] < 120 else None

"""Live data for the screens, shaped like screens/demo/data.json so the same templates render both."""

from __future__ import annotations

import calendar as cal
import hashlib
import json
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings
from .screens import LIVE_IMG, dither_photo
from .state import State
from .voice import recent_notes

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".webp"}


def _ago(seconds: float) -> str:
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _ago_words(seconds: float) -> str:
    a = _ago(seconds)
    return "just now" if a == "now" else f"{a} ago"


def _home(path: str) -> str:
    return re.sub(r"^/(?:Users|home)/[^/]+", "~", path)


def _span(seconds: float) -> str:
    h, m = int(seconds // 3600), int(seconds % 3600 // 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def _money(v: float) -> str:
    return f"{v:.0f}" if v >= 100 else f"{v:.2f}"


def _resets(resets_at: Any) -> str:
    if not resets_at:
        return "soon"
    try:
        ts = float(resets_at)
    except (TypeError, ValueError):
        ts = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00")).timestamp()
    left = max(0, ts - time.time())
    return f"{int(left // 86400)} days" if left >= 86400 else _span(left)


def short_id(key: str) -> str:
    return hashlib.sha1(key.encode()).hexdigest()[:8]


class Cached:
    """Fetch something slow at most every ttl seconds; keep the last good value on errors."""

    def __init__(self, ttl: int, fn):
        self.ttl, self.fn, self.value, self.at = ttl, fn, None, 0.0
        self._lock = threading.Lock()

    def get(self):
        with self._lock:
            if time.time() - self.at > self.ttl:
                try:
                    self.value = self.fn()
                except Exception:  # network or parse error: show the last good value
                    pass
                self.at = time.time()
            return self.value


class Live:
    def __init__(self, settings: Settings, state: State, usage, label):
        self.s, self.state, self.usage, self.label = settings, state, usage, label
        self.tz = ZoneInfo(settings.tz)
        self.weather = Cached(900, self._fetch_weather)
        self.events = Cached(600, self._fetch_events)

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # ---- the whole context ------------------------------------------------------
    def data(self, battery: int | None = None) -> dict[str, Any]:
        now = self.now()
        return {
            "now": now.strftime("%H:%M"),
            "battery": battery if battery is not None else 100,
            "usage": self._usage(),
            "sessions": self._sessions(),
            "today": self._today(now),
            "countdown": self._countdown(now.date()),
            "note": self._note(),
            "photo": self._photo(),
            "memory": self._memory(now.date()),
            "voice": self._voice(),
        }

    # ---- Claude -----------------------------------------------------------------
    def _usage(self) -> dict[str, Any]:
        u = self.usage.summary()
        limits = self.state.limits() or {}
        rows = []
        for key, name in (("five_hour", "5 hours"), ("seven_day", "Week")):
            info = limits.get(key) or {}
            pct = info.get("used_percentage")
            rows.append({"name": name, "pct": round(float(pct)) if pct is not None else 0,
                         "reset": _resets(info.get("resets_at")) if pct is not None else "no data"})
        days = [round(c, 2) for _, c in u.get("last14", [])] or [0.0] * 14
        for r in rows:
            r["reset"] = f"resets {r['reset']}" if r["reset"] != "no data" else "no data yet"
        return {"today": f"{u['today']['cost']:.2f}", "week": _money(u["week_cost"]),
                "month": _money(u["month_cost"]), "days": days,
                "limits": rows}

    def _sessions(self) -> list[dict[str, Any]]:
        out = []
        now = time.time()
        for s in self.state.sessions():
            perm = self.state.pending_permission(s["host"], s["session_id"]) if s["state"] == "waiting" else None
            item = {
                "id": perm["id"] if perm else short_id(f"{s['host']}:{s['session_id']}"),
                "project": s.get("project") or "?",
                "host": self.label(s["host"]),
                "ago": _ago(now - s.get("updated_at", now)),
                "asked": _ago_words(now - (perm["created"] if perm else s.get("updated_at", now))),
                "age": _span(now - s.get("started_at", now)),
                "state": s["state"] if s["state"] in ("waiting", "working", "idle") else "idle",
                "doing": s.get("message") or {"working": "Working", "idle": "Waiting for your next prompt",
                                              "waiting": "Needs your permission"}.get(s["state"], ""),
                "tool": perm["tool"] if perm else "Permission",
                "command": (perm["summary"] or perm["tool"]) if perm else (s.get("message") or "Answer in the terminal"),
                "where": _home(perm["cwd"]) if perm and perm["cwd"] else "",
                "approvable": bool(perm),
            }
            out.append(item)
        return out

    # ---- Today --------------------------------------------------------------------
    def _fetch_weather(self) -> dict[str, Any] | None:
        if not (self.s.lat and self.s.lon):
            return None
        import httpx

        r = httpx.get("https://api.open-meteo.com/v1/forecast", timeout=8, params={
            "latitude": self.s.lat, "longitude": self.s.lon, "timezone": self.s.tz,
            "current": "temperature_2m,weather_code", "hourly": "precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1})
        r.raise_for_status()
        return r.json()

    def _sky(self, w: dict[str, Any], now: datetime) -> str:
        probs = w.get("hourly", {}).get("precipitation_probability") or []
        for hour in range(now.hour, min(24, len(probs))):
            if probs[hour] is not None and probs[hour] >= 50:
                if hour <= now.hour:
                    return "Rain now"
                return f"Rain after {hour % 12 or 12} {'am' if hour < 12 else 'pm'}"
        code = (w.get("current") or {}).get("weather_code", 0)
        return {0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Cloudy", 45: "Fog", 48: "Fog"}.get(
            code, "Showers" if code >= 50 else "Cloudy")

    def _fetch_events(self) -> list[dict[str, Any]]:
        if not self.s.calendar_ics:
            return []
        import httpx
        import icalendar
        import recurring_ical_events

        r = httpx.get(self.s.calendar_ics, timeout=10, follow_redirects=True)
        r.raise_for_status()
        start = self.now().replace(hour=0, minute=0, second=0, microsecond=0)
        events = []
        for ev in recurring_ical_events.of(icalendar.Calendar.from_ical(r.content)).between(start, start + timedelta(days=4)):
            s, e = ev.get("DTSTART").dt, (ev.get("DTEND") or ev.get("DTSTART")).dt
            all_day = not isinstance(s, datetime)
            if all_day:
                s = datetime.combine(s, datetime.min.time(), self.tz)
                e = datetime.combine(e, datetime.min.time(), self.tz)
            events.append({"title": str(ev.get("SUMMARY", "Busy")), "where": str(ev.get("LOCATION", "") or ""),
                           "start": s.astimezone(self.tz).timestamp(), "end": e.astimezone(self.tz).timestamp(),
                           "all_day": all_day})
        return sorted(events, key=lambda x: x["start"])

    def _today(self, now: datetime) -> dict[str, Any]:
        w = self.weather.get()
        events = self.events.get() or []
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        hour = lambda ts: (ts - day0) / 3600  # noqa: E731
        todays = [e for e in events if not e["all_day"] and day0 <= e["start"] < day0 + 86400]
        line = [{"start": max(7, hour(e["start"])), "end": min(23, hour(e["end"])),
                 "title": e["title"], "time": datetime.fromtimestamp(e["start"], self.tz).strftime("%-H:%M")}
                for e in todays if hour(e["end"]) > 7 and hour(e["start"]) < 23]
        cards = []
        for e in events:
            if e["end"] <= now.timestamp() or len(cards) == 3:
                continue
            st = datetime.fromtimestamp(e["start"], self.tz)
            same_day = st.date() == now.date()
            if e["all_day"]:
                when, aside = ("Today" if same_day else st.strftime("%a")), "all day"
            elif same_day:
                mins = (e["start"] - now.timestamp()) / 60
                when, aside = st.strftime("%-H:%M"), ("now" if mins <= 0 else f"in {_span(mins * 60)}")
            else:
                when, aside = st.strftime("%a"), st.strftime("%-H:%M")
            cards.append({"when": when, "aside": aside, "what": e["title"], "sub": e["where"]})
        if not cards:
            cards = [{"when": "Free", "aside": "", "what": "Nothing on the calendar", "sub": ""}]
        out = {"day": now.strftime("%A"), "date": now.strftime("%-d %B"), "events": line,
               "now_h": round(now.hour + now.minute / 60, 2), "cards": cards,
               "temp": "", "hi": "", "lo": "", "sky": "", "inside": ""}
        if w:
            out.update(temp=round(w["current"]["temperature_2m"]), hi=round(w["daily"]["temperature_2m_max"][0]),
                       lo=round(w["daily"]["temperature_2m_min"][0]), sky=self._sky(w, now))
        return out

    # ---- countdowns ------------------------------------------------------------
    def _countdown(self, today: date) -> dict[str, Any]:
        try:
            items = json.loads(self.s.countdowns_file.read_text())
        except (OSError, json.JSONDecodeError):
            items = []
        items = [i for i in items if date.fromisoformat(i["date"]) >= today]
        if not items:
            return {"days": 0, "what": "Add a date to countdowns.json", "month": today.strftime("%B %Y"),
                    "first_weekday": cal.monthrange(today.year, today.month)[0],
                    "month_days": cal.monthrange(today.year, today.month)[1], "day": today.day, "next": []}
        main, rest = items[0], items[1:]
        d = date.fromisoformat(main["date"])
        return {"days": (d - today).days, "what": main.get("what") or f"days to {main['name']}",
                "month": d.strftime("%B %Y"), "first_weekday": cal.monthrange(d.year, d.month)[0],
                "month_days": cal.monthrange(d.year, d.month)[1], "day": d.day,
                "next": [{"name": i["name"], "days": (date.fromisoformat(i["date"]) - today).days} for i in rest[:2]]}

    # ---- fridge ---------------------------------------------------------------
    def _note(self) -> dict[str, Any]:
        f = self.s.fridge_dir / "note.json"
        try:
            n = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            return {"text": "Nothing pinned yet. Send a note to Hermes to put it here.", "from": "", "when": ""}
        return {"text": n["text"], "from": n.get("from", ""),
                "when": datetime.fromtimestamp(n.get("at", time.time()), self.tz).strftime("%-H:%M")}

    def photos(self) -> list[Path]:
        d = self.s.fridge_dir / "photos"
        return sorted((p for p in d.glob("*") if p.suffix.lower() in PHOTO_EXT), key=lambda p: p.stat().st_mtime,
                      reverse=True) if d.is_dir() else []

    def _meta(self, p: Path) -> dict[str, Any]:
        try:
            return json.loads(p.with_suffix(".json").read_text())
        except (OSError, json.JSONDecodeError):
            return {}

    def _dithered(self, p: Path, size: tuple[int, int], tag: str) -> str:
        out = LIVE_IMG / f"live-{tag}-{short_id(str(p) + str(p.stat().st_mtime))}.png"
        if not out.exists():
            meta = self._meta(p)
            dither_photo(p, out, size, center=tuple(meta.get("center", (0.5, 0.35))))
        return f"../img/{out.name}"

    def _photo(self) -> dict[str, Any]:
        photos = self.photos()
        if not photos:
            return {"full": "", "caption": "No photos yet", "byline": "Send one to Hermes", "hearted": False}
        idx = self.state.fridge().get("photo_index", 0) % len(photos)
        p = photos[idx]
        meta = self._meta(p)
        sent = meta.get("at", p.stat().st_mtime)
        byline = f"from {meta['from']}, {_ago_words(time.time() - sent)}" if meta.get("from") else ""
        return {"full": self._dithered(p, (800, 480), "full"), "caption": meta.get("caption", ""),
                "byline": byline, "hearted": p.name in self.state.fridge().get("hearts", [])}

    def _memory(self, today: date) -> dict[str, Any] | None:
        for p in self.photos():
            taken = self._meta(p).get("taken")
            if not taken:
                continue
            t = date.fromisoformat(taken[:10])
            if (t.month, t.day) == (today.month, today.day) and t.year < today.year:
                meta = self._meta(p)
                return {"half": self._dithered(p, (440, 480), "half"), "years": today.year - t.year,
                        "place": meta.get("place", meta.get("caption", "")), "line": meta.get("line", ""),
                        "date": t.strftime("%-d %b %Y")}
        return None

    # ---- voice ---------------------------------------------------------------
    def _voice(self) -> dict[str, Any]:
        notes = recent_notes(self.s, 1)
        if not notes:
            return {"kind": "Voice note", "title": "Hold the button and talk", "facts": [], "heard": "",
                    "seconds": "0:00"}
        n = notes[0]
        text = (self.s.notes_dir / n["file"]).read_text()
        heard = text.split("## Transcript", 1)[1].strip() if "## Transcript" in text else n["summary"]
        kind = {"todo": "To do", "idea": "Idea", "reminder": "Reminder"}.get(n["kind"], "Note")
        facts = [[str(i + 1), it] for i, it in enumerate(n["items"][:4])] or ([["", n["summary"]]] if n["summary"] else [])
        return {"kind": kind, "title": n["title"], "facts": facts, "heard": heard[:240], "seconds": "0:00",
                "file": n["file"]}

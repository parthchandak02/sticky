"""Claude Code usage from ccusage (local logs) plus pushes from other machines."""

from __future__ import annotations

import json
import shlex
import subprocess
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings


def _run_ccusage(settings: Settings, args: list[str]) -> dict[str, Any]:
    cmd = shlex.split(settings.ccusage_cmd) + args + ["--json", "-z", settings.tz]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=240, check=True)
    return json.loads(out.stdout)


def session_projects(projects_dir: Path, session_ids: set[str], cache: dict[str, str]) -> dict[str, str]:
    """Map session id -> project name using the cwd recorded in each session log."""
    missing = session_ids - cache.keys()
    if missing and projects_dir.is_dir():
        for log in projects_dir.glob("*/*.jsonl"):
            sid = log.stem
            if sid not in missing:
                continue
            name = log.parent.name
            try:
                with log.open() as fh:
                    for _, line in zip(range(40), fh):
                        cwd = json.loads(line).get("cwd")
                        if cwd:
                            name = Path(cwd).name
                            break
            except (OSError, json.JSONDecodeError):
                pass
            cache[sid] = name
    return {sid: cache.get(sid, "other") for sid in session_ids}


def collect_local(settings: Settings, cache: dict[str, str]) -> dict[str, Any]:
    today = datetime.now(ZoneInfo(settings.tz)).date()
    daily = _run_ccusage(settings, ["daily", "--since", (today - timedelta(days=40)).strftime("%Y%m%d")])
    sessions = _run_ccusage(settings, ["session", "--since", (today - timedelta(days=8)).strftime("%Y%m%d")])
    rows = sessions.get("session", [])
    projects = session_projects(settings.claude_projects_dir, {r["period"] for r in rows}, cache)
    return {"daily": daily.get("daily", []), "session": rows, "projects": projects}


def summarize(sources: dict[str, dict[str, Any]], tz: str) -> dict[str, Any]:
    """Combine per-host ccusage payloads into what the pages need."""
    today = datetime.now(ZoneInfo(tz)).date()
    by_day: dict[date, dict[str, float]] = defaultdict(lambda: {"cost": 0.0, "tokens": 0.0, "output": 0.0})
    models_today: dict[str, float] = defaultdict(float)
    projects_week: dict[str, float] = defaultdict(float)
    week_cutoff = time.time() - 7 * 86400

    for payload in sources.values():
        for row in payload.get("daily", []):
            d = date.fromisoformat(row["period"])
            by_day[d]["cost"] += row.get("totalCost", 0.0)
            by_day[d]["tokens"] += row.get("totalTokens", 0)
            by_day[d]["output"] += row.get("outputTokens", 0)
            if d == today:
                for m in row.get("modelBreakdowns", []):
                    models_today[m["modelName"]] += m.get("cost", 0.0)
        names = payload.get("projects", {})
        for row in payload.get("session", []):
            last = (row.get("metadata") or {}).get("lastActivity")
            if last and datetime.fromisoformat(last.replace("Z", "+00:00")).timestamp() >= week_cutoff:
                projects_week[names.get(row["period"], "other")] += row.get("totalCost", 0.0)

    def total(days: int) -> float:
        return sum(by_day[today - timedelta(days=i)]["cost"] for i in range(days))

    month = sum(v["cost"] for d, v in by_day.items() if d.year == today.year and d.month == today.month)
    last14 = [(today - timedelta(days=i), by_day[today - timedelta(days=i)]["cost"]) for i in range(13, -1, -1)]
    return {
        "today": {"cost": by_day[today]["cost"], "tokens": by_day[today]["tokens"], "output": by_day[today]["output"]},
        "week_cost": total(7),
        "month_cost": month,
        "last14": [(d.isoformat(), c) for d, c in last14],
        "models_today": sorted(models_today.items(), key=lambda kv: -kv[1]),
        "projects_week": sorted(projects_week.items(), key=lambda kv: -kv[1])[:8],
        "hosts": sorted(sources),
    }


class UsageCache:
    """Refreshes local ccusage data in the background so page renders stay fast."""

    def __init__(self, settings: Settings, host: str, pushes):
        self.settings = settings
        self.host = host
        self.pushes = pushes
        self.local: dict[str, Any] = {}
        self.error: str | None = None
        self.updated_at = 0.0
        self._project_cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def refresh(self) -> None:
        try:
            data = collect_local(self.settings, self._project_cache)
            with self._lock:
                self.local, self.error, self.updated_at = data, None, time.time()
        except Exception as exc:  # keep serving the last good data
            self.error = f"{type(exc).__name__}: {exc}"[:200]

    def loop(self) -> None:
        while True:
            self.refresh()
            time.sleep(self.settings.usage_refresh_seconds)

    def start(self) -> None:
        threading.Thread(target=self.loop, daemon=True, name="usage-refresh").start()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            sources = {self.host: self.local} if self.local else {}
        sources.update({h: p for h, p in self.pushes().items() if h != self.host})
        s = summarize(sources, self.settings.tz)
        s["updated_at"] = self.updated_at
        s["error"] = self.error
        return s

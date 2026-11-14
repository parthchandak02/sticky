"""Render the pages with made-up data into docs/assets/readme/ (used by the README)."""

import time
from datetime import date, timedelta
from pathlib import Path

from PIL import Image

from sticky_server.render import pages

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "readme"
TZ = "America/Los_Angeles"
now = time.time()
today = date.today()
costs = [31, 18, 44, 27, 12, 3, 22, 25, 61, 14, 2, 9, 19, 8]
usage = {
    "today": {"cost": 8.42, "tokens": 14_200_000, "output": 96_000},
    "week_cost": 156.10,
    "month_cost": 302.75,
    "last14": [((today - timedelta(days=13 - i)).isoformat(), c) for i, c in enumerate(costs)],
    "models_today": [("claude-opus-5-5", 7.9), ("claude-haiku-5-5", 0.52)],
    "projects_week": [("weather-app", 61.2), ("api-gateway", 44.8), ("dotfiles", 22.0), ("blog", 15.3),
                      ("notes-sync", 9.4), ("scratch", 3.4)],
    "hosts": ["laptop", "vps"],
    "updated_at": now - 120,
    "error": None,
}
sessions = [
    {"state": "waiting", "project": "api-gateway", "host": "vps", "updated_at": now - 40,
     "message": "Claude needs your permission to use Bash"},
    {"state": "working", "project": "weather-app", "host": "laptop", "updated_at": now - 15},
    {"state": "working", "project": "notes-sync", "host": "vps", "updated_at": now - 300},
    {"state": "idle", "project": "blog", "host": "laptop", "updated_at": now - 1900},
]
limits = {"five_hour": {"used_percentage": 38, "resets_at": now + 2 * 3600 + 900},
          "seven_day": {"used_percentage": 61, "resets_at": now + 3 * 86400 + 4 * 3600}}
notes = [
    {"title": "Book the venue tasting", "kind": "todo", "created": f"{today}T09:41:00",
     "summary": "Call the venue this week to set up a tasting for the menu, then confirm the headcount.",
     "items": ["Call the venue about a tasting date", "Confirm final headcount", "Ask about a vegetarian menu"]},
    {"title": "Idea: weekly review on the fridge", "kind": "idea", "created": f"{today}T08:10:00", "summary": "",
     "items": []},
    {"title": "Renew passport before March", "kind": "reminder", "created": f"{today}T07:55:00", "summary": "",
     "items": []},
]

OUT.mkdir(parents=True, exist_ok=True)
imgs = {
    "claude": pages.page_claude(usage, sessions, limits, TZ, 0),
    "projects": pages.page_projects(usage, TZ, 1),
    "notes": pages.page_notes(notes, TZ, 2),
}
for name, img in imgs.items():
    img.resize((1600, 960), Image.NEAREST).save(OUT / f"{name}.png", optimize=True)
    print(OUT / f"{name}.png")

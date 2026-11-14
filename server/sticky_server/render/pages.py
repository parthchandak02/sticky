"""The dashboard pages. Each returns a quantized 800x480 grayscale image."""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image

from .draw import (
    BLACK, DARK, H, LIGHT, W, WHITE, ago, bar, canvas, fit, font, footer, header, label, money,
    quantize, text_w, tokens, wrap,
)

PAGES = ["claude", "projects", "notes"]


def _clock(tz: str) -> str:
    return datetime.now(ZoneInfo(tz)).strftime("%a %d %b  %H:%M")


def _resets_in(resets_at: Any) -> str:
    if not resets_at:
        return ""
    try:
        ts = float(resets_at)
    except (TypeError, ValueError):
        ts = datetime.fromisoformat(str(resets_at).replace("Z", "+00:00")).timestamp()
    left = ts - time.time()
    if left <= 0:
        return "reset"
    h, m = int(left // 3600), int(left % 3600 // 60)
    return f"resets {h // 24}d {h % 24}h" if h >= 24 else f"resets {h}h {m:02d}m"


def _limit_row(d, y: int, name: str, info: dict | None) -> None:
    label(d, (20, y), name)
    if not info or info.get("used_percentage") is None:
        d.text((370, y), "no data yet", font=font(13), fill=DARK, anchor="ra")
        bar(d, (20, y + 20, 370, y + 40), 0)
        return
    pct = float(info["used_percentage"])
    d.text((370, y), f"{pct:.0f}%  {_resets_in(info.get('resets_at'))}", font=font(13, "semibold"),
           fill=BLACK, anchor="ra")
    bar(d, (20, y + 20, 370, y + 40), pct / 100, fill=BLACK if pct >= 80 else DARK)


def page_claude(usage: dict, sessions: list[dict], limits: dict | None, tz: str, idx: int) -> Image.Image:
    img, d = canvas()
    header(d, "CLAUDE CODE", _clock(tz))

    # left column: spend and limits
    label(d, (20, 60), "Today (API-equivalent)")
    d.text((18, 76), money(usage["today"]["cost"]), font=font(60, "bold"), fill=BLACK)
    d.text((20, 148), f"{tokens(usage['today']['tokens'])} tokens   {tokens(usage['today']['output'])} out",
           font=font(15), fill=DARK)
    label(d, (20, 180), "7 days")
    d.text((20, 196), money(usage["week_cost"]), font=font(26, "bold"), fill=BLACK)
    label(d, (200, 180), datetime.now(ZoneInfo(tz)).strftime("%B"))
    d.text((200, 196), money(usage["month_cost"]), font=font(26, "bold"), fill=BLACK)

    _limit_row(d, 240, "5-hour limit", (limits or {}).get("five_hour"))
    _limit_row(d, 290, "Weekly limit", (limits or {}).get("seven_day"))

    # 14 day chart
    days = usage["last14"]
    top = max([c for _, c in days] + [1])
    x0, y_base, chart_h, step = 20, H - 40, 76, 25
    label(d, (20, 342), "Last 14 days")
    d.text((370, 342), f"peak {money(top)}", font=font(12), fill=DARK, anchor="ra")
    for i, (ds, cost) in enumerate(days):
        h = int(chart_h * cost / top)
        x = x0 + i * step
        d.rectangle([x, y_base - max(h, 1), x + step - 7, y_base], fill=BLACK if i == len(days) - 1 else DARK)
        if i % 2 == 1 or i == len(days) - 1:
            d.text((x + (step - 7) / 2, y_base + 3), str(date.fromisoformat(ds).day), font=font(10), fill=DARK,
                   anchor="ma")

    # right column: sessions
    d.line([395, 56, 395, H - 34], fill=LIGHT, width=2)
    waiting = sum(s["state"] == "waiting" for s in sessions)
    label(d, (412, 60), f"Sessions  {len(sessions)}" + (f"   {waiting} waiting" if waiting else ""),
          fill=BLACK if waiting else DARK)
    y, now = 84, time.time()
    if not sessions:
        d.text((412, y + 10), "No active sessions", font=font(18, "semibold"), fill=DARK)
        d.text((412, y + 38), "Hooks report here once installed.", font=font(13), fill=DARK)
    for s in sessions:
        tall = s["state"] == "waiting" and s.get("message")
        row_h = 64 if tall else 44
        if y + row_h > H - 34:
            more = len(sessions) - sessions.index(s)
            d.text((412, y + 4), f"+{more} more", font=font(13, "semibold"), fill=DARK)
            break
        chip = {"waiting": ("WAIT", BLACK, WHITE), "working": ("RUN", DARK, WHITE)}.get(
            s["state"], ("IDLE", WHITE, BLACK))
        d.rounded_rectangle([412, y + 4, 462, y + 26], radius=4, fill=chip[1], outline=BLACK, width=1)
        d.text((437, y + 15), chip[0], font=font(12, "bold"), fill=chip[2], anchor="mm")
        meta = f"{s.get('host', '')}  {ago(now - s.get('updated_at', now))}"
        d.text((W - 20, y + 15), meta, font=font(12), fill=DARK, anchor="rm")
        name_w = W - 20 - text_w(d, meta, font(12)) - 12 - 474
        d.text((474, y + 15), fit(d, s.get("project", "?"), font(17, "semibold"), name_w),
               font=font(17, "semibold"), fill=BLACK, anchor="lm")
        if tall:
            d.text((474, y + 34), fit(d, s["message"], font(13), W - 20 - 474), font=font(13), fill=BLACK)
        y += row_h

    age = ago(now - usage["updated_at"]) if usage.get("updated_at") else ""
    status = "usage loading" if not age else ("usage just updated" if age == "now" else f"usage {age} ago")
    if usage.get("error"):
        status += "  (usage error)"
    footer(d, f"{', '.join(usage['hosts']) or 'no hosts'}   {status}", idx, len(PAGES))
    return quantize(img)


def page_projects(usage: dict, tz: str, idx: int) -> Image.Image:
    img, d = canvas()
    header(d, "PROJECTS THIS WEEK", _clock(tz))
    rows = usage["projects_week"]
    top = max([c for _, c in rows] + [1])
    label(d, (20, 60), "Spend by project, last 7 days")
    y = 86
    for name, cost in rows[:8]:
        d.text((20, y + 12), fit(d, name, font(17, "semibold"), 200), font=font(17, "semibold"), fill=BLACK,
               anchor="lm")
        bar(d, (230, y, 640, y + 24), cost / top, fill=DARK)
        d.text((W - 20, y + 12), money(cost), font=font(17, "bold"), fill=BLACK, anchor="rm")
        y += 36
    if not rows:
        d.text((20, 100), "No sessions in the last 7 days", font=font(18), fill=DARK)

    models = usage["models_today"][:3]
    if models:
        label(d, (20, H - 70), "Models today")
        x = 20
        for name, cost in models:
            t = f"{name.replace('claude-', '')}  {money(cost)}"
            d.text((x, H - 50), t, font=font(15, "semibold"), fill=BLACK)
            x += text_w(d, t, font(15, "semibold")) + 30
    footer(d, "cost is API-equivalent, from ccusage", idx, len(PAGES))
    return quantize(img)


def page_notes(notes: list[dict], tz: str, idx: int) -> Image.Image:
    img, d = canvas()
    header(d, "VOICE NOTES", _clock(tz))
    if not notes:
        d.text((20, 90), "No notes yet", font=font(26, "bold"), fill=BLACK)
        d.text((20, 130), "Hold the AI button and talk. The note lands here and in your notes folder.",
               font=font(15), fill=DARK)
    y = 58
    for i, n in enumerate(notes):
        if i == 0:
            kind = n["kind"].upper()
            d.rounded_rectangle([20, y + 2, 30 + text_w(d, kind, font(12, "bold")) + 10, y + 22], radius=4,
                                fill=BLACK)
            d.text((30, y + 12), kind, font=font(12, "bold"), fill=WHITE, anchor="lm")
            d.text((W - 20, y + 12), n["created"][5:16].replace("T", " "), font=font(12), fill=DARK, anchor="rm")
            d.text((20, y + 28), fit(d, n["title"], font(28, "bold"), W - 40), font=font(28, "bold"), fill=BLACK)
            yy = y + 66
            for line in wrap(d, n["summary"], font(16), W - 40, 2):
                d.text((20, yy), line, font=font(16), fill=BLACK)
                yy += 22
            yy += 6
            for item in n["items"][:4]:
                d.rectangle([22, yy + 5, 32, yy + 15], outline=BLACK, width=2)
                d.text((42, yy), fit(d, item, font(16), W - 62), font=font(16), fill=BLACK)
                yy += 24
            y = yy + 8
            d.line([20, y, W - 20, y], fill=LIGHT, width=1)
            y += 8
            continue
        if y + 34 > H - 30:
            break
        d.text((20, y + 4), fit(d, n["title"], font(16, "semibold"), 560), font=font(16, "semibold"), fill=BLACK)
        d.text((W - 20, y + 6), f"{n['kind']}  {n['created'][5:10]}", font=font(12), fill=DARK, anchor="ra")
        y += 30
    footer(d, "notes are Markdown files on the server", idx, len(PAGES))
    return quantize(img)

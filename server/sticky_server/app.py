"""HTTP API for the Sticky: dashboard images, Claude Code hook intake, voice notes, firmware files."""

from __future__ import annotations

import hashlib
import json
import secrets
import socket
import time
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from rich.console import Console

from . import config
from .render import draw, pages
from .live import Live
from .screens import Renderer
from .state import State
from .usage import UsageCache
from .voice import VoiceJobs, recent_notes

console = Console()
settings = config.load()
HOST = socket.gethostname().split(".")[0]
state = State(settings.state_file)
usage = UsageCache(settings, HOST, state.usage_pushes)
voice = VoiceJobs(settings)
renderer = Renderer()

app = FastAPI(title="sticky-server", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    usage.start()
    if not settings.token:
        console.print("[yellow]STICKY_TOKEN is empty: every endpoint is open. Fine on a home LAN only.[/]")


def auth(request: Request) -> None:
    if not settings.token:
        return
    supplied = (
        request.headers.get("x-sticky-token")
        or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.query_params.get("token", "")
    )
    if not secrets.compare_digest(supplied, settings.token):
        raise HTTPException(401, "bad token")


# ---- dashboard ------------------------------------------------------------
def _label(host: str) -> str:
    return settings.host_labels.get(host, host)


live = Live(settings, state, usage, lambda h: settings.host_labels.get(h, h))


def _labelled_usage() -> dict:
    u = usage.summary()
    u["hosts"] = [_label(h) for h in u["hosts"]]
    return u


def render_page(name: str):
    idx = pages.PAGES.index(name)
    if name == "claude":
        sessions = [{**s, "host": _label(s.get("host", ""))} for s in state.sessions()]
        return pages.page_claude(_labelled_usage(), sessions, state.limits(), settings.tz, idx)
    if name == "projects":
        return pages.page_projects(_labelled_usage(), settings.tz, idx)
    return pages.page_notes(recent_notes(settings), settings.tz, idx)


def _page_name(name: str) -> str:
    if name.isdigit():
        return pages.PAGES[int(name) % len(pages.PAGES)]
    if name not in pages.PAGES:
        raise HTTPException(404, f"pages: {pages.PAGES}")
    return name


@app.get("/display/{name}.png", dependencies=[Depends(auth)])
def display_png(name: str) -> Response:
    return Response(draw.to_png(render_page(_page_name(name))), media_type="image/png",
                    headers={"Cache-Control": "no-store"})


@app.get("/display/{name}.bmp", dependencies=[Depends(auth)])
def display_bmp(request: Request, name: str, rotate: int = 0, bits: int = 8) -> Response:
    if request.client:
        state.device_seen(request.client.host, request.headers.get("x-sticky-fw", ""), name)
    if rotate not in (0, 90, 180, 270):
        raise HTTPException(400, "rotate must be 0, 90, 180 or 270")
    if bits not in (2, 8):
        raise HTTPException(400, "bits must be 2 or 8")
    return Response(draw.to_bmp(render_page(_page_name(name)), rotate, bits), media_type="image/bmp",
                    headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def preview(request: Request) -> str:
    token = request.query_params.get("token", "")
    q = f"?token={token}" if token else ""
    imgs = "".join(
        f'<figure><img src="/display/{p}.png{q}" width="800" height="480" alt="{p}"><figcaption>{p}</figcaption></figure>'
        for p in pages.PAGES
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Sticky preview</title>
<meta http-equiv="refresh" content="60"><style>
body{{background:#ddd;font:14px system-ui;margin:24px;color:#111}}
figure{{margin:0 0 24px}} img{{max-width:100%;height:auto;border:1px solid #888;background:#fff}}
</style></head><body><h1>Sticky pages</h1>{imgs}</body></html>"""


# ---- screens (HTML renderer) ------------------------------------------------
# frame -> (template, extra context). Every frame is 800x480 except the reader.
FRAMES = {
    "board": ("board", {"title": "The Board"}),
    "approve": ("approve", {"title": "Permission"}),
    "today": ("today", {"title": "Today"}),
    "countdown": ("countdown", {"title": "Counting down"}),
    "photo": ("photo", {"folio": False}),
    "onthisday": ("onthisday", {"folio": False}),
    "note": ("note", {"title": "On the fridge"}),
    "listening": ("voice", {"title": "Voice", "mode": "listening"}),
    "voice_result": ("voice", {"title": "Voice note", "mode": "result"}),
    "art": ("art", {"folio": False}),
}
FULL_REFRESH_SECONDS = 30 * 60


TELEMETRY = {"x-sticky-battery": "battery", "x-sticky-charging": "charging", "x-sticky-temp": "temp_c",
             "x-sticky-humidity": "humidity", "x-sticky-rssi": "rssi", "x-sticky-orient": "orient"}


def _telemetry(request: Request) -> dict[str, Any]:
    out = {}
    for header, key in TELEMETRY.items():
        v = request.headers.get(header)
        if v is not None:
            try:
                out[key] = float(v) if "." in v else int(v)
            except ValueError:
                out[key] = v[:16]
    return out


def _render_frame(frame: str, request: Request, progress: int = 0):
    if frame not in FRAMES:
        raise HTTPException(404, f"frames: {sorted(FRAMES)}")
    template, extra = FRAMES[frame]
    tel = _telemetry(request)
    if request.client:
        state.device_seen(request.client.host, request.headers.get("x-sticky-fw", ""), frame, telemetry=tel)
    dev = state.latest_device() or {}
    d = live.data(int(dev["battery"]) if isinstance(dev.get("battery"), (int, float)) else None)
    if isinstance(dev.get("temp_c"), (int, float)) and time.time() - dev.get("seen_at", 0) < 3 * 3600:
        d["today"]["inside"] = f"{round(dev['temp_c'])}°"
    if frame == "onthisday" and not d["memory"]:
        raise HTTPException(404, "no photo from this day")
    deck = list(settings.deck)
    ctx = {"d": d, "deck_len": len(deck), "deck_idx": deck.index(frame) if frame in deck else -1,
           "progress": max(0, min(24, progress)), **extra}
    if frame in ("board", "photo", "note"):
        ctx["toast"] = state.flash()
    return renderer.render(template, frame, ctx)


@app.get("/screen/deck", dependencies=[Depends(auth)])
def screen_deck(request: Request) -> dict[str, Any]:
    """Everything the firmware should do that can change without a new build: the pages, how long to
    sleep, whether to chime, hold length, how often to clean the panel."""
    sessions = state.sessions()
    waiting = [s for s in sessions if s["state"] == "waiting"]
    busy = any(s["state"] == "working" for s in sessions)
    if request.client:
        state.device_seen(request.client.host, request.headers.get("x-sticky-fw", ""), "deck",
                          telemetry=_telemetry(request))
    return {
        "deck": list(settings.deck),
        "frames": sorted(FRAMES),
        "start": "approve" if waiting else settings.deck[0],
        # Sleep less while Claude is busy, so a prompt shows up soon even on battery.
        "sleep_seconds": 120 if waiting else (300 if busy else FULL_REFRESH_SECONDS),
        "chime": bool(waiting),
        "hold_ms": 1000,
        "full_refresh_every": 8,
        "firmware_manifest": "/firmware/sticky-os.json",
    }


@app.get("/screen/{frame}.png", dependencies=[Depends(auth)])
def screen_png(frame: str, request: Request, progress: int = 0) -> Response:
    img, _ = _render_frame(frame, request, progress)
    return Response(draw.to_png(img), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/screen/{frame}.bmp", dependencies=[Depends(auth)])
def screen_bmp(frame: str, request: Request, progress: int = 0, rotate: int = 0, bits: int = 2) -> Response:
    if rotate not in (0, 90, 180, 270) or bits not in (2, 8):
        raise HTTPException(400, "rotate 0/90/180/270, bits 2 or 8")
    img, _ = _render_frame(frame, request, progress)
    body = draw.to_bmp(img, rotate, bits)
    etag = '"' + hashlib.sha1(body).hexdigest()[:16] + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(body, media_type="image/bmp", headers={"Cache-Control": "no-store", "ETag": etag})


@app.get("/screen/{frame}.json", dependencies=[Depends(auth)])
def screen_json(frame: str, request: Request, progress: int = 0) -> dict[str, Any]:
    """Tap and hold areas for the frame, in panel pixels."""
    _, hotspots = _render_frame(frame, request, progress)
    return {"frame": frame, "hotspots": hotspots}


@app.post("/api/action", dependencies=[Depends(auth)])
async def screen_action(request: Request) -> dict[str, Any]:
    """The device reports a tap or a completed hold. Returns the frame to show next and how to refresh."""
    body = await _json(request)
    frame, action = str(body.get("frame", "")), str(body.get("action", ""))
    verb, _, arg = action.partition(":")
    nxt, refresh = frame, "partial"
    if verb in ("allow", "deny"):
        perm = state.permission(arg)
        if not perm:
            raise HTTPException(404, "that prompt is gone")
        if state.decide_permission(arg, verb):
            state.flash(f"{'Allowed' if verb == 'allow' else 'Denied'}, {perm['project']}")
        nxt, refresh = "board", "full"
    elif action == "open:approve":
        nxt, refresh = "approve", "full"
    elif action == "back":
        nxt, refresh = "board", "full"
    elif action == "heart":
        if frame == "photo":
            photos = live.photos()
            if photos:
                name = photos[state.fridge().get("photo_index", 0) % len(photos)].name
                state.fridge_update(hearts=sorted(set(state.fridge().get("hearts", [])) | {name}))
        else:
            state.fridge_update(note_heart=time.time())
        state.flash("Heart sent")
    elif action == "photo:next":
        state.fridge_update(photo_index=state.fridge().get("photo_index", 0) + 1)
        nxt = "photo"
    elif action == "reply":
        nxt, refresh = "listening", "full"
    elif action in ("done", "undo"):
        if action == "undo":
            f = live.data()["voice"].get("file")
            if f:
                (settings.notes_dir / f).unlink(missing_ok=True)
        nxt, refresh = settings.deck[0], "full"
    else:
        raise HTTPException(400, f"unknown action {action!r}")
    return {"next": nxt, "refresh": refresh}


# ---- permission prompts answered on the Sticky ------------------------------
@app.post("/api/permission", dependencies=[Depends(auth)])
async def permission_open(request: Request) -> dict[str, Any]:
    """Called by hooks/sticky-permission.py when Claude Code asks for permission."""
    event = await _json(request)
    state.apply_hook({**event, "hook_event_name": "PermissionRequest"})
    return {"id": state.open_permission(event), "wait": settings.approve_wait}


@app.get("/api/permission/{pid}", dependencies=[Depends(auth)])
def permission_wait(pid: str, wait: float = 20) -> dict[str, Any]:
    """Long-poll: returns as soon as the prompt is answered, or after `wait` seconds."""
    p = state.wait_permission(pid, max(0.0, min(wait, 30.0)))
    if not p:
        raise HTTPException(404, "unknown prompt")
    return {"id": pid, "decision": p["decision"]}


@app.post("/api/permission/{pid}/expire", dependencies=[Depends(auth)])
def permission_expire(pid: str) -> dict[str, bool]:
    return {"ok": state.decide_permission(pid, "expired")}


# ---- fridge: notes and photos sent from Hermes or a phone -------------------
@app.post("/api/fridge/note", dependencies=[Depends(auth)])
async def fridge_note(request: Request) -> dict[str, bool]:
    body = await _json(request)
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "text is required")
    (settings.fridge_dir / "note.json").write_text(json.dumps(
        {"text": text[:160], "from": str(body.get("from", ""))[:12], "at": time.time()}))
    state.fridge_update(note_heart=None)
    return {"ok": True}


@app.post("/api/fridge/photo", dependencies=[Depends(auth)])
async def fridge_photo(file: UploadFile, caption: str = "", sender: str = "", taken: str = "",
                       place: str = "") -> dict[str, str]:
    data = await file.read()
    suffix = "." + (file.filename or "p.jpg").rsplit(".", 1)[-1].lower()
    if suffix not in (".jpg", ".jpeg", ".png", ".webp") or len(data) < 1000:
        raise HTTPException(400, "send a jpg, png or webp photo")
    d = settings.fridge_dir / "photos"
    d.mkdir(parents=True, exist_ok=True)
    name = time.strftime("%Y%m%d-%H%M%S")
    (d / f"{name}{suffix}").write_bytes(data)
    (d / f"{name}.json").write_text(json.dumps({"caption": caption[:40], "from": sender[:12], "at": time.time(),
                                                  "taken": taken[:10], "place": place[:40]}))
    state.fridge_update(photo_index=0)
    return {"id": name}


# ---- Claude Code intake ---------------------------------------------------
async def _json(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"bad json: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "expected an object")
    return body


@app.post("/api/hooks/claude", dependencies=[Depends(auth)])
async def hook(request: Request) -> dict[str, Any]:
    sess = state.apply_hook(await _json(request))
    return {"ok": True, "state": sess and sess["state"]}


@app.post("/api/statusline", dependencies=[Depends(auth)])
async def statusline(request: Request) -> dict[str, bool]:
    state.apply_statusline(await _json(request))
    return {"ok": True}


@app.post("/api/usage/push", dependencies=[Depends(auth)])
async def usage_push(request: Request, host: str) -> dict[str, bool]:
    state.apply_usage_push(host, await _json(request))
    return {"ok": True}


@app.get("/api/sessions", dependencies=[Depends(auth)])
def api_sessions() -> list[dict[str, Any]]:
    return state.sessions()


@app.get("/api/devices", dependencies=[Depends(auth)])
def api_devices() -> list[dict[str, Any]]:
    return state.devices()


@app.get("/api/usage", dependencies=[Depends(auth)])
def api_usage() -> dict[str, Any]:
    return {**usage.summary(), "limits": state.limits()}


# ---- voice ----------------------------------------------------------------
@app.post("/api/voice", dependencies=[Depends(auth)])
async def voice_upload(request: Request, file: UploadFile | None = None) -> dict[str, str]:
    if file is not None:
        data, suffix = await file.read(), "." + (file.filename or "a.wav").rsplit(".", 1)[-1]
    else:
        data = await request.body()
        ctype = request.headers.get("content-type", "")
        suffix = {"audio/mpeg": ".mp3", "audio/mp4": ".m4a", "audio/ogg": ".ogg"}.get(ctype, ".wav")
    if len(data) < 1000:
        raise HTTPException(400, "audio too short or missing")
    return {"id": voice.submit(data, suffix)}


@app.get("/api/voice/{note_id}", dependencies=[Depends(auth)])
def voice_status(note_id: str) -> dict[str, Any]:
    job = voice.get(note_id)
    if not job:
        raise HTTPException(404, "unknown id")
    return job


@app.get("/api/notes", dependencies=[Depends(auth)])
def api_notes(limit: int = 20) -> list[dict[str, Any]]:
    return recent_notes(settings, limit)


# ---- firmware (wireless updates) -------------------------------------------
@app.get("/firmware/{name}")
def firmware(name: str) -> Response:
    path = (settings.firmware_dir / name).resolve()
    if path.parent != settings.firmware_dir.resolve() or not path.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(path)


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "host": HOST, "usage_updated_at": usage.updated_at, "usage_error": usage.error})


def main() -> None:
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()

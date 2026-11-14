"""HTTP API for the Sticky: dashboard images, Claude Code hook intake, voice notes, firmware files."""

from __future__ import annotations

import json
import secrets
import socket
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from rich.console import Console

from . import config
from .render import draw, pages
from .state import State
from .usage import UsageCache
from .voice import VoiceJobs, recent_notes

console = Console()
settings = config.load()
HOST = socket.gethostname().split(".")[0]
state = State(settings.state_file)
usage = UsageCache(settings, HOST, state.usage_pushes)
voice = VoiceJobs(settings)

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
def render_page(name: str):
    idx = pages.PAGES.index(name)
    if name == "claude":
        return pages.page_claude(usage.summary(), state.sessions(), state.limits(), settings.tz, idx)
    if name == "projects":
        return pages.page_projects(usage.summary(), settings.tz, idx)
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
def display_bmp(name: str, rotate: int = 0) -> Response:
    if rotate not in (0, 90, 180, 270):
        raise HTTPException(400, "rotate must be 0, 90, 180 or 270")
    return Response(draw.to_bmp(render_page(_page_name(name)), rotate), media_type="image/bmp",
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

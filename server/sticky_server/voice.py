"""Voice notes: audio -> text (whisper.cpp) -> tidy note (Claude Code CLI) -> Markdown file."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import Settings

CLEANUP_PROMPT = """You turn a rough voice memo transcript into a clean note.
Return ONLY a JSON object, no prose, with keys:
  "title": short title (max 6 words),
  "kind": one of "todo", "idea", "note", "reminder",
  "summary": one or two sentences in plain words,
  "items": list of short action items or key points (may be empty),
  "when": any date or time mentioned, as written, else "".
Fix obvious transcription errors. Do not invent facts. Never use em dashes or en dashes.

Transcript:
"""


def transcribe(settings: Settings, audio: Path) -> str:
    if settings.stt_backend != "whispercpp":
        raise RuntimeError(f"unknown STT backend {settings.stt_backend}")
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "in.wav"
        subprocess.run(
            [settings.ffmpeg_bin, "-y", "-loglevel", "error", "-i", str(audio), "-ar", "16000", "-ac", "1", str(wav)],
            check=True,
            timeout=120,
        )
        out = Path(tmp) / "out"
        cmd = [settings.whisper_bin, "-m", str(settings.whisper_model), "-f", str(wav), "-otxt", "-of", str(out), "-np"]
        if settings.vocab:
            cmd += ["--prompt", "Words that may come up: " + settings.vocab + "."]
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            timeout=600,
        )
        return (out.with_suffix(".txt")).read_text().strip()


def _parse_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("no JSON in cleanup output")
    return json.loads(match.group(0))


def cleanup(settings: Settings, transcript: str) -> dict[str, Any]:
    if settings.cleanup_backend == "none" or not transcript:
        return {"title": "Voice note", "kind": "note", "summary": transcript, "items": [], "when": ""}
    if settings.cleanup_backend != "claude-cli":
        raise RuntimeError(f"unknown cleanup backend {settings.cleanup_backend}")
    env = {**os.environ, "STICKY_HOOK_DISABLE": "1"}  # keep this run off the session board
    vocab = f"Names and words the speaker often uses: {settings.vocab}.\n" if settings.vocab else ""
    proc = subprocess.run(
        [settings.claude_bin, "-p", "--model", settings.cleanup_model, "--output-format", "json"],
        input=CLEANUP_PROMPT.replace("Transcript:\n", vocab + "Transcript:\n") + transcript,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=tempfile.gettempdir(),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {proc.stderr[:200]}")
    result = json.loads(proc.stdout).get("result", "")
    note = _parse_json(result)
    note.setdefault("items", [])
    note.setdefault("when", "")
    return note


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "note"


def write_markdown(settings: Settings, note_id: str, note: dict[str, Any], transcript: str) -> Path:
    now = datetime.now(ZoneInfo(settings.tz))
    path = settings.notes_dir / f"{now:%Y-%m-%d-%H%M}-{_slug(note.get('title', ''))}.md"
    lines = [
        "---",
        f"id: {note_id}",
        f"created: {now.isoformat(timespec='seconds')}",
        f"kind: {note.get('kind', 'note')}",
        f"title: {json.dumps(note.get('title', 'Voice note'))}",
        "source: sticky",
        "---",
        "",
        f"# {note.get('title', 'Voice note')}",
        "",
        note.get("summary", ""),
        "",
    ]
    if note.get("when"):
        lines += [f"When: {note['when']}", ""]
    lines += [f"- [ ] {item}" if note.get("kind") == "todo" else f"- {item}" for item in note.get("items", [])]
    lines += ["", "## Transcript", "", transcript, ""]
    path.write_text("\n".join(lines))
    return path


class VoiceJobs:
    """Runs uploads through the pipeline in the background; the device polls by id."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit(self, audio_bytes: bytes, suffix: str = ".wav") -> str:
        note_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        audio = self.settings.audio_dir / f"{note_id}{suffix}"
        audio.write_bytes(audio_bytes)
        with self._lock:
            self.jobs[note_id] = {"id": note_id, "status": "queued", "created_at": time.time()}
        threading.Thread(target=self._run, args=(note_id, audio), daemon=True).start()
        return note_id

    def _set(self, note_id: str, **kw: Any) -> None:
        with self._lock:
            self.jobs[note_id].update(kw)

    def _run(self, note_id: str, audio: Path) -> None:
        try:
            self._set(note_id, status="transcribing")
            transcript = transcribe(self.settings, audio)
            self._set(note_id, status="cleaning", transcript=transcript)
            try:
                note = cleanup(self.settings, transcript)
            except Exception as exc:  # fall back to the raw transcript rather than losing the note
                note = {"title": "Voice note", "kind": "note", "summary": transcript, "items": [], "when": ""}
                self._set(note_id, cleanup_error=str(exc)[:200])
            path = write_markdown(self.settings, note_id, note, transcript)
            self._set(note_id, status="done", note=note, path=str(path))
        except Exception as exc:
            self._set(note_id, status="error", error=f"{type(exc).__name__}: {exc}"[:300])

    def get(self, note_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self.jobs.get(note_id)
            return dict(job) if job else None


def recent_notes(settings: Settings, limit: int = 6) -> list[dict[str, Any]]:
    notes = []
    for path in sorted(settings.notes_dir.glob("*.md"), reverse=True)[:limit]:
        text = path.read_text()
        meta = dict(re.findall(r"^(\w+): (.*)$", text.split("---", 2)[1], re.M)) if text.startswith("---") else {}
        body = text.split("---", 2)[-1]
        summary = next((ln for ln in body.splitlines() if ln and not ln.startswith(("#", "-", "When:"))), "")
        items = [ln[2:].removeprefix("[ ] ") for ln in body.split("## Transcript")[0].splitlines() if ln.startswith("- ")]
        title = meta.get("title", path.stem)
        try:
            title = json.loads(title)
        except (json.JSONDecodeError, TypeError):
            pass
        notes.append({"title": title, "kind": meta.get("kind", "note"), "created": meta.get("created", ""),
                      "summary": summary, "items": items, "file": path.name})
    return notes

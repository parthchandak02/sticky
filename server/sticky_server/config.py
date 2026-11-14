"""Settings from environment (and an optional .env next to the repo root)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSETS = REPO_ROOT / "assets"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if value and key not in os.environ:
            os.environ[key] = value


def _path(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser()


def _get(key: str, default: str) -> str:
    return os.environ.get(key) or default


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    token: str
    data_dir: Path
    tz: str
    ccusage_cmd: str
    claude_projects_dir: Path
    usage_refresh_seconds: int
    stt_backend: str
    whisper_bin: str
    whisper_model: Path
    ffmpeg_bin: str
    cleanup_backend: str
    claude_bin: str
    cleanup_model: str
    vocab: str
    host_labels: dict

    @property
    def notes_dir(self) -> Path:
        return self.data_dir / "notes"

    @property
    def audio_dir(self) -> Path:
        return self.data_dir / "audio"

    @property
    def firmware_dir(self) -> Path:
        return self.data_dir / "firmware"

    @property
    def state_file(self) -> Path:
        return self.data_dir / "state.json"


def load() -> Settings:
    _load_dotenv(Path(os.environ.get("STICKY_ENV_FILE", REPO_ROOT / ".env")))
    s = Settings(
        host=_get("STICKY_HOST", "0.0.0.0"),
        port=int(_get("STICKY_PORT", "8787")),
        token=_get("STICKY_TOKEN", ""),
        data_dir=_path(_get("STICKY_DATA_DIR", "~/.local/share/sticky")),
        tz=_get("STICKY_TZ", "America/Los_Angeles"),
        ccusage_cmd=_get("STICKY_CCUSAGE_CMD", "npx -y ccusage@20.0.50"),
        claude_projects_dir=_path(_get("STICKY_CLAUDE_PROJECTS_DIR", "~/.claude/projects")),
        usage_refresh_seconds=int(_get("STICKY_USAGE_REFRESH_SECONDS", "300")),
        stt_backend=_get("STICKY_STT_BACKEND", "whispercpp"),
        whisper_bin=_get("STICKY_WHISPER_BIN", "whisper-cli"),
        whisper_model=_path(_get("STICKY_WHISPER_MODEL", "~/.local/share/sticky/models/ggml-base.en.bin")),
        ffmpeg_bin=_get("STICKY_FFMPEG_BIN", "ffmpeg"),
        cleanup_backend=_get("STICKY_CLEANUP_BACKEND", "claude-cli"),
        claude_bin=_get("STICKY_CLAUDE_BIN", "claude"),
        cleanup_model=_get("STICKY_CLEANUP_MODEL", "haiku"),
        vocab=_get("STICKY_VOCAB", ""),
        host_labels=dict(
            kv.split("=", 1) for kv in _get("STICKY_HOST_LABELS", "").split(",") if "=" in kv
        ),
    )
    for d in (s.data_dir, s.notes_dir, s.audio_dir, s.firmware_dir):
        d.mkdir(parents=True, exist_ok=True)
    return s

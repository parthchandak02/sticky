"""Permission round trip, device actions and fridge uploads, against the real app with a temp data dir."""

import io
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("STICKY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("STICKY_TOKEN", "t")
    monkeypatch.setenv("STICKY_ENV_FILE", str(tmp_path / "none.env"))
    monkeypatch.setenv("STICKY_CCUSAGE_CMD", "true")
    for mod in [m for m in sys.modules if m.startswith("sticky_server")]:
        del sys.modules[mod]
    from sticky_server import app as appmod

    with TestClient(appmod.app, headers={"X-Sticky-Token": "t"}) as c:
        c.appmod = appmod
        yield c


def test_permission_allow_from_device(client):
    event = {"session_id": "s1", "cwd": "/home/me/apps/tandem", "tool_name": "Bash",
             "summary": "npm run deploy", "sticky_host": "mini"}
    pid = client.post("/api/permission", json=event).json()["id"]
    sessions = client.appmod.live.data()["sessions"]
    assert sessions[0]["state"] == "waiting" and sessions[0]["id"] == pid and sessions[0]["approvable"]
    result = {}
    t = threading.Thread(target=lambda: result.update(client.get(f"/api/permission/{pid}?wait=10").json()))
    t.start()
    time.sleep(0.3)
    r = client.post("/api/action", json={"frame": "approve", "action": f"allow:{pid}"}).json()
    t.join(5)
    assert result["decision"] == "allow" and r == {"next": "board", "refresh": "full"}
    assert client.appmod.state.flash().startswith("Allowed, tandem")
    # a second answer is ignored
    client.post("/api/action", json={"frame": "approve", "action": f"deny:{pid}"})
    assert client.get(f"/api/permission/{pid}?wait=0").json()["decision"] == "allow"


def test_permission_expires_without_answer(client):
    pid = client.post("/api/permission", json={"session_id": "s2", "tool_name": "Edit"}).json()["id"]
    assert client.get(f"/api/permission/{pid}?wait=0.2").json()["decision"] is None
    assert client.post(f"/api/permission/{pid}/expire").json()["ok"]
    r = client.post("/api/action", json={"frame": "approve", "action": f"allow:{pid}"})
    assert r.status_code == 200 and client.get(f"/api/permission/{pid}?wait=0").json()["decision"] == "expired"


def test_needs_token(client):
    assert client.get("/api/permission/x", headers={"X-Sticky-Token": "bad"}).status_code == 401
    assert client.post("/api/action", json={}, headers={"X-Sticky-Token": "bad"}).status_code == 401


def test_fridge_note_and_photo(client):
    assert client.post("/api/fridge/note", json={"text": "Dumplings tonight?", "from": "P."}).json()["ok"]
    assert client.appmod.live.data()["note"]["text"] == "Dumplings tonight?"
    buf = io.BytesIO()
    Image.new("RGB", (1200, 900), (120, 160, 90)).save(buf, "JPEG")
    r = client.post("/api/fridge/photo", files={"file": ("a.jpg", buf.getvalue(), "image/jpeg")},
                    params={"caption": "Garden", "sender": "S"})
    assert r.status_code == 200
    photo = client.appmod.live.data()["photo"]
    assert photo["caption"] == "Garden" and photo["full"].startswith("../img/live-full-")
    client.post("/api/action", json={"frame": "photo", "action": "heart"})
    assert client.appmod.live.data()["photo"]["hearted"]


def test_hook_script_relays_decision(client, tmp_path):
    """Run hooks/sticky-permission.py against a real server process and answer from 'the device'."""
    port = 8796
    env = {**os.environ, "STICKY_DATA_DIR": str(tmp_path / "srv"), "STICKY_TOKEN": "t", "STICKY_PORT": str(port),
           "STICKY_HOST": "127.0.0.1", "STICKY_ENV_FILE": str(tmp_path / "none.env"), "STICKY_CCUSAGE_CMD": "true"}
    srv = subprocess.Popen([sys.executable, "-m", "sticky_server.app"], env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        import httpx

        base = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                httpx.get(base + "/healthz", timeout=0.5)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        hook_env = {**os.environ, "STICKY_URL": base, "STICKY_TOKEN": "t", "STICKY_APPROVE_WAIT": "10",
                    "STICKY_CLIENT_ENV": str(tmp_path / "none.env")}
        event = {"session_id": "abc", "cwd": "/x/tandem", "hook_event_name": "PermissionRequest",
                 "tool_name": "Bash", "tool_input": {"command": "rm -rf build"}}
        hook = subprocess.Popen([sys.executable, str(REPO / "hooks" / "sticky-permission.py")], env=hook_env,
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        hook.stdin.write(json.dumps(event))
        hook.stdin.close()
        h = {"X-Sticky-Token": "t"}
        pid = None
        for _ in range(50):
            sess = httpx.get(base + "/api/sessions", headers=h).json()
            if sess and sess[0]["state"] == "waiting":
                break
            time.sleep(0.1)
        perms = json.loads((tmp_path / "srv" / "state.json").read_text())["permissions"]
        pid = next(iter(perms))
        assert perms[pid]["summary"] == "rm -rf build"
        httpx.post(base + "/api/action", headers=h, json={"frame": "approve", "action": f"deny:{pid}"})
        out = json.loads(hook.stdout.read())
        assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"
        assert hook.wait(10) == 0
    finally:
        srv.terminate()
        srv.wait(5)

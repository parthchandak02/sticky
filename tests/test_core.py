import time
from pathlib import Path

from sticky_server.render import draw, pages
from sticky_server.state import State
from sticky_server.usage import summarize


def test_hook_states(tmp_path: Path):
    st = State(tmp_path / "s.json")
    base = {"session_id": "a", "cwd": "/x/proj", "sticky_host": "mac"}
    st.apply_hook({**base, "hook_event_name": "SessionStart"})
    assert st.sessions()[0]["state"] == "idle"
    st.apply_hook({**base, "hook_event_name": "UserPromptSubmit"})
    assert st.sessions()[0]["state"] == "working"
    st.apply_hook({**base, "hook_event_name": "Notification", "notification_type": "permission_prompt",
                   "message": "Claude needs your permission to use Bash"})
    s = st.sessions()[0]
    assert s["state"] == "waiting" and "permission" in s["message"]
    st.apply_hook({**base, "hook_event_name": "Stop"})
    assert st.sessions()[0]["state"] == "idle" and "message" not in st.sessions()[0]
    st.apply_hook({**base, "hook_event_name": "SessionEnd"})
    assert st.sessions() == []
    # persisted
    assert State(tmp_path / "s.json").data["sessions"]


def test_waiting_sorts_first(tmp_path: Path):
    st = State(tmp_path / "s.json")
    st.apply_hook({"session_id": "a", "hook_event_name": "UserPromptSubmit", "sticky_host": "h"})
    st.apply_hook({"session_id": "b", "hook_event_name": "PermissionRequest", "tool_name": "Bash", "sticky_host": "h"})
    assert [s["session_id"] for s in st.sessions()] == ["b", "a"]


def test_summarize_merges_hosts():
    today = time.strftime("%Y-%m-%d", time.gmtime())
    row = {"period": today, "totalCost": 10.0, "totalTokens": 100, "outputTokens": 5,
           "modelBreakdowns": [{"modelName": "claude-opus-5-5", "cost": 10.0}]}
    s = summarize({"a": {"daily": [row]}, "b": {"daily": [row]}}, "UTC")
    assert s["today"]["cost"] == 20.0 and s["hosts"] == ["a", "b"]


def test_pages_render_four_levels():
    usage = summarize({}, "UTC") | {"updated_at": time.time(), "error": None}
    for img in (pages.page_claude(usage, [], None, "UTC", 0), pages.page_projects(usage, "UTC", 1),
                pages.page_notes([], "UTC", 2)):
        assert img.size == (800, 480)
        assert set(img.getdata()) <= set(draw.LEVELS)
    assert draw.to_bmp(img)[:2] == b"BM"

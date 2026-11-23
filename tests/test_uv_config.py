import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_uv_only_resolves_versions_at_least_7_days_old():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["tool"]["uv"]["exclude-newer"] == "7 days"
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    assert lock["options"]["exclude-newer-span"] == "P7D"

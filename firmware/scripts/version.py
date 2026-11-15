"""PlatformIO pre-script: stamp the build with a version and write it next to firmware.bin.

Version: os-<git short sha>[-dirty]-<UTC yyyymmddHHMM>. scripts/publish_firmware.py reads
sticky_version.txt to write the over-the-air manifest.
"""

import os
import subprocess
import time
from pathlib import Path

Import("env")  # noqa: F821  (PlatformIO injects it)

root = Path(env["PROJECT_DIR"])  # noqa: F821
if os.environ.get("STICKY_GIT_SHA"):  # set when building from a copy without .git
    sha, dirty = os.environ["STICKY_GIT_SHA"], False
else:
  try:
    sha = subprocess.check_output(["git", "rev-parse", "--short=8", "HEAD"], cwd=root, text=True).strip()
    dirty = subprocess.call(["git", "diff", "--quiet", "--", "."], cwd=root) != 0
  except Exception:
    sha, dirty = "nogit", False
version = f"os-{sha}{'-dirty' if dirty else ''}-{time.strftime('%Y%m%d%H%M', time.gmtime())}"
env.Append(CPPDEFINES=[("STICKY_FW_VERSION", f'\\"{version}\\"')])  # noqa: F821
build_dir = Path(env.subst("$BUILD_DIR"))  # noqa: F821
build_dir.mkdir(parents=True, exist_ok=True)
(build_dir / "sticky_version.txt").write_text(version + "\n")
print(f"sticky firmware version {version}")

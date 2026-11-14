#!/usr/bin/env bash
# Build the Board firmware, publish it on this server, and wait until the Sticky runs it.
#   scripts/ship_firmware.sh [path/to/sticky-firmware]
# The device checks for updates on every page refresh (about once a minute while Board is open),
# installs the new build by itself, restarts, and reopens Board.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
FW="${1:-${STICKY_FIRMWARE_DIR:-$REPO/../sticky-firmware}}"
BUILD="$FW/.pio/build/sticky_board"
TOKEN="$(grep '^STICKY_TOKEN=' "$REPO/.env" | cut -d= -f2 || true)"
PORT="$(grep '^STICKY_PORT=' "$REPO/.env" | cut -d= -f2 || true)"; PORT="${PORT:-8787}"
TIMEOUT="${STICKY_SHIP_TIMEOUT:-600}"

echo "== building $FW"
(cd "$FW" && pio run -e sticky_board | grep -E "Sticky Board build|SUCCESS|FAILED|error:")
VERSION="$(tr -d '\n' < "$BUILD/sticky_version.txt")"
echo "== publishing $VERSION"
(cd "$REPO" && uv run python scripts/publish_firmware.py "$BUILD")

echo "== waiting up to ${TIMEOUT}s for a Sticky to report $VERSION (Board must be open)"
deadline=$(( $(date +%s) + TIMEOUT ))
while [ "$(date +%s)" -lt "$deadline" ]; do
  if curl -s -H "X-Sticky-Token: $TOKEN" "http://127.0.0.1:$PORT/api/devices" | grep -q "\"$VERSION\""; then
    echo "== done: device is running $VERSION"; exit 0
  fi
  sleep 10
done
echo "== timed out: the device has not reported $VERSION. Is Board open and on Wi-Fi?"; exit 1

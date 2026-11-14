#!/usr/bin/env bash
# Run the Sticky server as a background service that starts at login/boot.
#   macOS: a launchd user agent (~/Library/LaunchAgents/com.sticky.server.plist)
#   Linux: a systemd user service (~/.config/systemd/user/sticky.service), lingering enabled
# Usage: scripts/install_service.sh [--uninstall]
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd -P)"
UV="$(command -v uv)"

# Services should not run from an external volume: macOS blocks background access to removable
# drives behind a permission prompt, and the drive may mount late. Deploy a clone on the boot disk.
# Update it later with: scripts/install_service.sh (pulls the latest commit and restarts).
DEPLOY="${STICKY_DEPLOY_DIR:-}"
if [ -z "$DEPLOY" ] && [ "$(uname -s)" = Darwin ] && [[ "$REPO" == /Volumes/* ]]; then
  DEPLOY="$HOME/.local/share/sticky/app"
fi
if [ -n "$DEPLOY" ] && [ "${1:-}" != "--uninstall" ]; then
  if [ -d "$DEPLOY/.git" ]; then
    git -C "$DEPLOY" pull -q --ff-only
  else
    mkdir -p "$(dirname "$DEPLOY")" && git clone -q "$REPO" "$DEPLOY"
  fi
  [ -f "$REPO/.env" ] && cp "$REPO/.env" "$DEPLOY/.env"
  (cd "$DEPLOY" && "$UV" sync -q)
  echo "deployed $(git -C "$DEPLOY" rev-parse --short HEAD) to $DEPLOY"
  REPO="$DEPLOY"
fi
# ccusage needs node, and voice cleanup needs the claude CLI; capture their dirs for the service PATH
EXTRA_PATH=""
for bin in node claude whisper-cli ffmpeg; do
  p="$(command -v "$bin" 2>/dev/null || true)"
  [ -n "$p" ] && EXTRA_PATH="$EXTRA_PATH:$(dirname "$p")"
done
SVC_PATH="$(dirname "$UV")${EXTRA_PATH}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

[ -n "$DEPLOY" ] || (cd "$REPO" && "$UV" sync -q)
case "$(uname -s)" in
  Darwin)
    PLIST="$HOME/Library/LaunchAgents/com.sticky.server.plist"
    LOG="$HOME/Library/Logs/sticky-server.log"
    launchctl bootout "gui/$(id -u)/com.sticky.server" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do launchctl print "gui/$(id -u)/com.sticky.server" >/dev/null 2>&1 || break; sleep 0.5; done
    if [ "${1:-}" = "--uninstall" ]; then rm -f "$PLIST"; echo "removed $PLIST"; exit 0; fi
    sed -e "s|__UV__|$UV|g" -e "s|__REPO__|$REPO|g" -e "s|__PATH__|$SVC_PATH|g" -e "s|__LOG__|$LOG|g" \
      "$REPO/deploy/launchd/com.sticky.server.plist" > "$PLIST"
    launchctl bootstrap "gui/$(id -u)" "$PLIST"
    echo "running under launchd; log: $LOG"
    ;;
  Linux)
    UNIT="$HOME/.config/systemd/user/sticky.service"
    if [ "${1:-}" = "--uninstall" ]; then
      systemctl --user disable --now sticky.service || true; rm -f "$UNIT"; echo "removed $UNIT"; exit 0
    fi
    mkdir -p "$(dirname "$UNIT")"
    sed -e "s|__UV__|$UV|g" -e "s|__REPO__|$REPO|g" -e "s|__PATH__|$SVC_PATH|g" \
      "$REPO/deploy/systemd/sticky.service" > "$UNIT"
    loginctl enable-linger "$(id -un)" 2>/dev/null || true
    systemctl --user daemon-reload
    systemctl --user enable --now sticky.service
    echo "running under systemd; logs: journalctl --user -u sticky -f"
    ;;
  *) echo "unsupported OS"; exit 1 ;;
esac

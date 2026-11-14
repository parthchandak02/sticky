#!/bin/sh
# Claude Code hook: forward the event JSON to the Sticky server.
# Never blocks or fails Claude: posts in the background with a 2 s cap and always exits 0.
# Config: ~/.config/sticky/client.env with STICKY_URL and STICKY_TOKEN.
[ "${STICKY_HOOK_DISABLE:-}" = "1" ] && exit 0
CONF="${STICKY_CLIENT_ENV:-$HOME/.config/sticky/client.env}"
[ -f "$CONF" ] && . "$CONF"
[ -n "${STICKY_URL:-}" ] || exit 0
command -v curl >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

payload="$(python3 -c '
import json, socket, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
d["sticky_host"] = socket.gethostname().split(".")[0]
for k in ("tool_input", "tool_response", "transcript_path", "prompt"):
    d.pop(k, None)  # keep commands, file contents and prompts off the wire
print(json.dumps(d))
')" || exit 0
[ -n "$payload" ] || exit 0

( printf '%s' "$payload" | curl -s -m 2 -o /dev/null -X POST \
    -H 'Content-Type: application/json' -H "X-Sticky-Token: ${STICKY_TOKEN:-}" \
    --data-binary @- "$STICKY_URL/api/hooks/claude" ) >/dev/null 2>&1 &
exit 0

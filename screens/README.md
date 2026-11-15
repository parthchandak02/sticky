# Screens

Every screen the Sticky shows is an HTML page, rendered by headless Chromium on the server and snapped to the panel's four grays. What you see in `out/` is byte for byte what the device would draw.

## How a screen gets to the glass

1. **Template.** `templates/<screen>.html.j2` plus data (`demo/data.json` here, live state on the server).
2. **Render.** Chromium screenshots it at 800x480 (or 480x800 in portrait) at 1x.
3. **Snap.** Every pixel goes to the nearest of 0, 85, 170, 255. Photos are error-diffused to those four levels first, so they stay smooth.
4. **Hotspots.** Every element with `data-tap` or `data-hold` becomes a rectangle with an action name.
5. **Device.** Fetches the image (2-bit BMP, 96 KB) and the hotspot list, draws, then maps touches to actions and posts them back.

```
uv run python scripts/render_screens.py           # all frames into screens/out/
python3 -m http.server 8786                       # then open /prototype/
node scripts/proto_test.mjs http://127.0.0.1:8786/prototype/ cook/stills/proto
```

## Live server

`sticky-server` renders the same templates from live data (`server/sticky_server/live.py`, `screens.py`).

| Method | Path | Purpose |
|---|---|---|
| GET | `/screen/deck` | Pages to swipe through and how long to sleep |
| GET | `/screen/{frame}.bmp?bits=2` | The frame for the panel (96 KB); `.png` for a preview; `?progress=0..24` fills the hold dial |
| GET | `/screen/{frame}.json` | Its tap and hold areas |
| POST | `/api/action` | `{"frame", "action"}` from a tap or a finished hold; returns `{"next", "refresh"}` |
| POST | `/api/permission` | From `hooks/sticky-permission.py`: a Claude prompt waiting for an answer |
| GET | `/api/permission/{id}?wait=20` | The hook waits here for allow or deny |
| POST | `/api/fridge/note` | `{"text", "from"}`, the note on the fridge (Hermes can send it) |
| POST | `/api/fridge/photo` | multipart `file`, with `caption`, `sender`, `taken`, `place` |

Frames: `board`, `approve`, `today`, `countdown`, `photo`, `onthisday` (only when a photo was taken on this day), `note`, `listening`, `voice_result`, `art`. The reader is still demo only.

Data: Claude sessions and limits from the hooks, spend from ccusage, weather from Open-Meteo (`STICKY_LAT`, `STICKY_LON`), calendar from a private iCal URL (`STICKY_CALENDAR_ICS`), countdowns from `$STICKY_DATA_DIR/countdowns.json` (`[{"name", "date", "what"}]`, first is the big one), notes and photos from `$STICKY_DATA_DIR/fridge/`.

### Answering Claude from the Sticky

Install on a machine with `python3 scripts/install_client.py --url ... --token ... --approve 45`. When Claude asks for permission, the prompt shows on the Sticky; hold to allow or tap Deny. If nobody answers in 45 seconds the terminal asks as usual, and any error does the same: the hook never allows anything by itself. Only the tool name, folder and a one-line summary (the command or file path) leave the machine.

## Gestures

| Gesture | Where | Does |
|---|---|---|
| Tap | any hotspot | its action (open, deny, heart, reply, page edges) |
| Hold 1 s | allow dial, Hold to allow | approve a Claude permission; letting go early does nothing |
| Swipe left, right | landscape pages | next or previous page (full refresh) |
| Swipe up, down | photos, reader | more on this page (partial refresh) |
| Up, Down buttons | anywhere | same as swiping pages |
| Hold AI button | anywhere | record a voice note; let go to send |
| Turn to portrait | accelerometer | opens the book |
| No input 90 s | anywhere | art sleep screen |

## Refresh rules

- **Full refresh** (about 1.4 s, flashes): changing pages, opening a screen, waking.
- **Partial refresh** (about 0.3 s, no flash): hold progress, hearts, toasts, page turns in the reader, the voice timer. A full refresh clears the faint ghosting partial refreshes leave.

## Files

| Path | Holds |
|---|---|
| `templates/base.css` | The type, the four tones, folio, buttons, textures |
| `templates/*.html.j2` | One template per screen |
| `flow.json` | Frames (template + state), the page deck, tap and hold actions, swipe targets |
| `out/manifest.json` | Frames with their hotspots, read by the prototype and later the firmware |
| `demo/` | Demo data and a CC0 stand-in photo, see `demo/CREDITS.md` |

# Contributing

Thanks for looking. Sticky is small on purpose: the server draws every screen, and the firmware
stays a thin, careful client. Most changes are a template, a bit of live data, or a firmware fix.

## Getting set up

```bash
git clone --recursive https://github.com/parthchandak02/sticky && cd sticky
uv sync
uv run playwright install chromium
uv run pytest                      # server tests, including a real hook round trip
uv run python scripts/render_screens.py
python3 -m http.server 8786        # open http://127.0.0.1:8786/prototype/
```

You do not need the device to work on screens: the prototype shows the real frames with real
e-paper timing, and `node scripts/proto_test.mjs http://127.0.0.1:8786/prototype/ /tmp/proto`
drives every gesture and checks where each one lands.

## Where things go

| Change | Files |
|---|---|
| A new or changed screen | `screens/templates/`, `screens/demo/data.json`, `screens/flow.json` |
| Live data for a screen | `server/sticky_server/live.py`, then the frame in `FRAMES` in `app.py` |
| What a tap or hold does | `/api/action` in `server/sticky_server/app.py` |
| Device behaviour | `firmware/src/`, design notes in `firmware/PLAN.md` |
| Hardware support | upstream in the [FreeInk SDK](https://github.com/Free-Ink/freeink-sdk) |

## House rules

- **Screens are for e-paper.** Four tones only, text in ink or graphite, nothing under 15 px that
  matters, no hatching, no animation. Short labels over sentences.
- **Every touch target is a `data-tap` or `data-hold` element.** The firmware knows nothing about
  layouts; it only reads the touch map.
- **Anything that runs a command needs a hold, never a tap.**
- **Demo data is fictional.** No real names, photos, places or dates in `screens/demo/`.
- **Firmware updates must stay safe over the air.** Keep the trial boot, the checksum and the
  board tag; never break `ota::markGood()` being called after the first server frame.
- **Tests pass** (`uv run pytest`, `proto_test.mjs` 19/19) and the firmware builds
  (`cd firmware && pio run`).

After a visual change, refresh the README images with
`uv run python scripts/readme_images.py` and include them in the same pull request.

## Reporting a problem

Open an issue with what you did, what you expected and what happened. For the device, paste the
output of `status` from the serial console (`pio device monitor`) and the panel name it logs at
boot (SSD1677 or SSD2677).

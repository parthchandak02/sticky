# sticky

Sticky is a Claude Code dashboard and fridge note on a Seeed reTerminal Sticky. The Python
server draws every 800x480 screen. The ESP32 firmware is a thin client: it fetches a frame,
draws it on the e-paper panel, and sends taps, holds, swipes, keys, and voice back. Parth
uses it on one device.

## Setup
```
uv sync --locked --group dev
```
A fresh worktree is ready to run pytest after this one command. `uv` must already be installed.
Screen design also needs `uv run playwright install chromium`. Firmware work needs
`git clone --recursive` (the FreeInk SDK is a submodule) and PlatformIO. CI installs neither.

## Check before you commit
```
uv run ruff check .
uv run pytest
```
All must pass. CI runs the same commands on every PR and on push to main.

Firmware is not built in CI. The PlatformIO toolchain is a custom ESP32 platform download plus
the submodule, which is not a small CI step. Firmware changes always need Parth's review.
Do not ship or publish firmware from a factory run.

`scripts/proto_test.mjs` drives the browser prototype. It is not part of CI. Run it when a
gesture or screen flow changes, after rendering screens and serving `prototype/`.

## Layout
- `server/sticky_server/`: HTTP app, screen renderer, live data, sessions, voice
- `screens/`: Jinja templates, demo data, flow, rendered frames
- `prototype/`: the device in a browser
- `firmware/`: PlatformIO firmware and `PLAN.md` (`freeink-sdk/` is a submodule)
- `hooks/`: Claude Code hook, permission hook, status line
- `scripts/`: render, prototype test, install, firmware publish
- `tests/`: pytest for the server

## Conventions
- Screens use four tones only. Anything that runs a command needs a hold, never a tap.
- Touch targets are `data-tap` or `data-hold`. The firmware only reads the touch map.
- Demo data is fictional. No real names, photos, places, or dates in `screens/demo/`.
- Firmware updates stay safe over the air: trial boot, checksum, and board tag stay intact.
- No em dashes or en dashes in user-facing text or docs.

## Do not touch
- `.env*`, `STICKY_TOKEN`, `firmware/platformio.local.ini`, production data, deploy config
  unless the task says so.

## Factory
This repo is worked on by Parth's software factory. Factory agents also follow
`~/projects/infra/factory-hq/constitution.md`.
Every change is review-only: the factory never auto-merges this repo.
Firmware changes are review-only forever, even after CI is green, because CI does not build
the firmware.

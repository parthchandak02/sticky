# Sticky firmware

Our own firmware for the Seeed reTerminal Sticky. It replaces the CrossMux fork.

## Idea

The server draws every screen. The device is a fast, careful terminal for it:

- it shows what the server sends, with the right refresh;
- it turns touches, buttons, rotation and voice into events and sends them;
- it sleeps whenever it can, and updates itself over the air.

New screens, new pages and new behaviour ship as server changes. Firmware changes are for hardware
and protocol, and they arrive over the air too.

## Hardware (from the FreeInk SDK's Sticky profile)

| Part | Chip | Notes |
|---|---|---|
| SoC | ESP32-S3R8 | 8 MB PSRAM, 32 MB flash |
| Display | SSD1677, 800x480, 4 grays | 24-pin FPC; full refresh about 1.5 s, partial about 0.3 s (1-bit) |
| Touch | GT911 | own I2C bus, active-high TOUCH_EN, digitizer rotated against the panel |
| Buttons | AI, Up, Down | plus reset |
| Mic | PDM | I2S PDM RX |
| Buzzer | LEDC tone on GPIO48 | no speaker |
| Sensors | PCF8563 RTC, SHT40 temp/humidity, LSM6DS3TR-C IMU | shared sensor I2C bus |
| Battery | BQ27220 fuel gauge, BQ25616 charger, 750 mAh | gauge SCL is GPIO0 (strapping pin) |
| Power | 74AHC1G79 latch | drive PWR_HOLD (GPIO45) and PWR_LOCK (GPIO46) high at start; release to power off |
| USB | WCH bridge to UART0 | flashing and logs |
| SD | shared SPI with the panel | not needed by this firmware |

## Building blocks

- **FreeInk SDK** (MIT, `Free-Ink/freeink-sdk`, pinned as a submodule): panel driver and waveforms, touch,
  buttons, mic, buzzer, sensors, gauge. It is the same layer that runs the Sticky under CrossMux today.
- **PlatformIO** with Arduino on ESP-IDF, as CrossMux builds it on the Mac mini.
- **Our code** (`firmware/src/`): the app. About 2,000 to 3,000 lines when done.

## Protocol (server side already exists)

| Device does | Endpoint |
|---|---|
| Ask what to show and how | `GET /screen/deck` (pages, sleep time, chime, config) |
| Fetch a frame | `GET /screen/{frame}.bmp?bits=2` (96 KB, native 2-bit) |
| Fetch its touch map | `GET /screen/{frame}.json` (tap and hold areas) |
| Report a tap, hold, swipe or button | `POST /api/action` -> `{next, refresh}` |
| Upload a voice note | `POST /api/voice`, then `GET /api/voice/{id}` |
| Check for firmware | `GET /firmware/sticky.json` |

Every request carries `X-Sticky-Token`, `X-Sticky-Fw`, `X-Sticky-Battery`, and the room
temperature and humidity, so the server can show them.

Frames are cached by ETag, so an unchanged screen costs one small request and no refresh.

## Flexibility: what the server can change without new firmware

- The page deck, its order, and which page to show after any action.
- Refresh choice per frame (full or partial) and how often to force a clean full refresh.
- Wake interval, quiet hours, and urgent wake (a permission prompt shortens the sleep).
- Chime on or off, and which events chime.
- Hold length and the hold progress ring position (sent with the touch map).
- Swipe and button targets per frame.
- Orientation per frame (portrait reader).

Device-side settings live in NVS and can be set over USB serial (`wifi add`, `server`, `token`,
`chime off`) or pushed from the server.

## Interaction model

| Input | Device does |
|---|---|
| Tap | finds the smallest hotspot under the finger, posts its action |
| Hold | draws the ring locally with 1-bit partial refreshes, posts on completion; letting go early does nothing |
| Swipe left or right | next or previous page in the deck |
| Swipe up or down | frame's own scroll action (photos, reader) |
| Up, Down | same as swipes |
| AI button held | records from the mic into PSRAM; on release uploads and shows the result |
| Turned to portrait | posts `orient:portrait`, the server answers with the reader |
| Idle | sleeps; wakes on a button, on touch, or on the timer |

Feedback is instant even when the server is slow: a touched control gets a small partial-refresh
mark at once, then the next frame arrives.

## Power

- On battery: deep sleep between refreshes. Wake on the timer (server decides, default 30 min,
  shorter while Claude sessions are active), on any button, or on touch.
- On USB power: stay awake and long-poll, so a permission prompt shows within seconds.
- A full clean refresh every N partial ones, against ghosting.

## Updates and safety

- Two app slots (A/B). A new build runs once on trial; it marks itself good only after it has drawn
  a frame from the server. If it crashes or cannot reach the server three times, the bootloader
  rolls back to the last good build.
- A version that failed once is never retried.
- Every update is checked: ESP image checksum, SHA-256 from the manifest, and a board tag.
- Holding Up while powering on stays on the last good build and skips updates (recovery).
- Before the first flash, the whole 32 MB flash is backed up, so CrossMux can be restored exactly.
- Only the first install uses USB. Everything after it is over the air.

## Phases

| # | What | Done when |
|---|---|---|
| 0 | Back up the flash; project skeleton; display, buttons, power latch, serial console | A test screen draws and buttons log |
| 1 | Wi-Fi (several networks), settings in NVS, fetch and draw frames, deck navigation | The live Board shows and Up/Down change pages |
| 2 | OTA with rollback and the server manifest | A build installs itself from the server and survives a bad one |
| 3 | Touch: taps, holds with the local ring, swipes; actions | Allow a Claude prompt from the device |
| 4 | Voice: PDM recording, upload, result screen | A spoken task lands in notes |
| 5 | Power: deep sleep, wake sources, USB-powered long-poll, chime, sensors, battery | Days on battery, prompts in seconds on USB |
| 6 | Rotation and the reader; offline cache of the last frames | Turn it and read; it shows the last page without Wi-Fi |

Phase 2 comes before touch on purpose: once OTA works, every later phase ships without a cable.

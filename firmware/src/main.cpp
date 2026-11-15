// Sticky firmware: shows sticky-server's screens and sends back what you do with them.
//
// Cycle: wake -> join Wi-Fi -> ask the server for the deck -> fetch the current frame (ETag, so an
// unchanged screen costs one small request and no refresh) -> handle touch, keys and voice ->
// on battery, sleep until a key or the server's wake time; on USB power, stay awake and poll.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <BoardConfig.h>
#include <InputManager.h>
#include <esp32-hal-log.h>
#include <esp_ota_ops.h>
#include <esp_system.h>

#include "console.h"
#include "display.h"
#include "frame.h"
#include "gesture.h"
#include "hw.h"
#include "net.h"
#include "ota.h"
#include "settings.h"
#include "voice.h"

namespace {
constexpr const char* TAG = "main";
constexpr uint32_t kAwakeOnBatteryMs = 60000;   // stay up a minute after the last touch on battery
constexpr uint32_t kPollOnUsbMs = 5000;         // on USB power, check for changes this often
constexpr uint32_t kOtaEveryMs = 6UL * 3600 * 1000;
constexpr int kRingRadius = 40;

// Kept across deep sleep, so a timer wake can skip straight to "has anything changed?".
RTC_DATA_ATTR char rtcFrame[24] = "board";
RTC_DATA_ATTR char rtcEtag[40] = "";
RTC_DATA_ATTR uint16_t rtcPartials = 0;
RTC_DATA_ATTR uint32_t rtcWakes = 0;

InputManager input;
GestureReader gestures;
Frame current;

struct Deck {
  std::vector<std::string> pages{"board"};
  std::string start = "board";
  uint32_t sleepSeconds = 1800;
  bool chime = false;
  uint32_t holdMs = 1000;
  uint16_t fullEvery = 8;
  std::string manifest = "/firmware/sticky-os.json";
} deck;

bool serverOk = false;
bool lastChime = false;
uint32_t lastActivity = 0, lastPoll = 0, lastOta = 0;
const Hotspot* holdTarget = nullptr;

bool fetchDeck() {
  net::Response r = net::get("/screen/deck", "", 8000);
  if (r.status != 200 || !r.body) {
    net::freeBody(r);
    return false;
  }
  JsonDocument doc;
  const bool ok = !deserializeJson(doc, reinterpret_cast<const char*>(r.body));
  net::freeBody(r);
  if (!ok) return false;
  deck.pages.clear();
  for (JsonVariantConst p : doc["deck"].as<JsonArrayConst>()) deck.pages.push_back(p.as<const char*>());
  if (deck.pages.empty()) deck.pages.push_back("board");
  deck.start = doc["start"] | deck.pages[0].c_str();
  deck.sleepSeconds = doc["sleep_seconds"] | 1800;
  deck.chime = doc["chime"] | false;
  deck.holdMs = doc["hold_ms"] | 1000;
  deck.fullEvery = doc["full_refresh_every"] | 8;
  deck.manifest = doc["firmware_manifest"] | "/firmware/sticky-os.json";
  gestures.holdMs = deck.holdMs;
  return true;
}

// Fetch a frame and show it. refresh: "full", "partial", or "auto" (full every N partials).
// Returns false when the server could not be reached.
bool show(const std::string& name, const char* refresh = "auto", bool force = false) {
  const bool same = name == current.name;
  net::Response img = net::get("/screen/" + name + ".bmp?bits=2", (same && !force) ? current.etag : "", 15000);
  if (img.status == 304) {
    net::freeBody(img);
    return true;  // nothing changed on the server: no refresh at all
  }
  if (img.status != 200 || !img.body) {
    ESP_LOGW(TAG, "frame %s: HTTP %d", name.c_str(), img.status);
    net::freeBody(img);
    return false;
  }
  Frame next;
  const bool decoded = decodeBmp2(img.body, img.len, next);
  next.etag = img.etag;
  net::freeBody(img);
  if (!decoded) return false;
  next.name = name;
  net::Response hs = net::get("/screen/" + name + ".json", "", 10000);
  if (hs.status == 200 && hs.body) parseHotspots(reinterpret_cast<const char*>(hs.body), next);
  net::freeBody(hs);

  bool full = strcmp(refresh, "full") == 0 || rtcPartials >= deck.fullEvery || next.w != current.w;
  if (strcmp(refresh, "partial") == 0 && rtcPartials < deck.fullEvery * 2) full = false;
  display::showFrame(next, full);
  rtcPartials = full ? 0 : rtcPartials + 1;

  std::swap(current.pix, next.pix);
  current.w = next.w;
  current.h = next.h;
  current.name = name;
  current.etag = next.etag;
  current.hotspots = next.hotspots;
  strlcpy(rtcFrame, name.c_str(), sizeof(rtcFrame));
  strlcpy(rtcEtag, current.etag.c_str(), sizeof(rtcEtag));
  ota::markGood();  // drew a server frame: this build works
  return true;
}

void postAction(const std::string& action) {
  JsonDocument body;
  body["frame"] = current.name;
  body["action"] = action;
  std::string json;
  serializeJson(body, json);
  net::Response r = net::postJson("/api/action", json, 15000);
  std::string next = current.name, refresh = "partial";
  if (r.status == 200 && r.body) {
    JsonDocument doc;
    if (!deserializeJson(doc, reinterpret_cast<const char*>(r.body))) {
      next = doc["next"] | current.name.c_str();
      refresh = doc["refresh"] | "partial";
    }
  } else {
    ESP_LOGW(TAG, "action %s: HTTP %d", action.c_str(), r.status);
  }
  net::freeBody(r);
  show(next, refresh.c_str(), true);
}

int deckIndex() {
  for (size_t i = 0; i < deck.pages.size(); i++)
    if (deck.pages[i] == current.name) return static_cast<int>(i);
  return -1;
}

void page(int step) {
  int i = deckIndex();
  const int n = static_cast<int>(deck.pages.size());
  i = (i < 0) ? 0 : ((i + step) % n + n) % n;
  show(deck.pages[i], "full");
}

// Touch arrives in panel pixels (800x480 landscape); portrait frames are turned a quarter left.
void toFrame(int px, int py, int& fx, int& fy) {
  if (current.w == 800) {
    fx = px;
    fy = py;
  } else {
    fx = 479 - py;
    fy = px;
  }
}

void handleGesture(const Gesture& g) {
  switch (g.type) {
    case GestureType::Down: {
      holdTarget = current.hit(g.x, g.y, true);
      if (holdTarget && !holdTarget->hold) holdTarget = nullptr;
      gestures.armHold(holdTarget != nullptr);
      break;
    }
    case GestureType::HoldProgress:
      if (holdTarget) display::ring(current, g.x, g.y, kRingRadius, g.progress);
      break;
    case GestureType::HoldDone:
      if (holdTarget) {
        display::ring(current, g.x, g.y, kRingRadius, 1.0f);
        postAction(holdTarget->action);
        holdTarget = nullptr;
      }
      break;
    case GestureType::HoldCancel:
      display::restore(current, g.x - kRingRadius - 10, g.y - kRingRadius - 10, 2 * kRingRadius + 20,
                       2 * kRingRadius + 20);
      holdTarget = nullptr;
      break;
    case GestureType::Tap: {
      const Hotspot* h = current.hit(g.x, g.y, false);
      if (h && !h->hold) {  // a tap never triggers a hold-only control (allow needs the hold)
        display::tapMark(current, g.x, g.y);
        postAction(h->action);
      }
      break;
    }
    case GestureType::SwipeLeft: page(+1); break;
    case GestureType::SwipeRight: page(-1); break;
    case GestureType::SwipeUp:
    case GestureType::SwipeDown:
      if (current.name == "photo" || current.name == "onthisday") postAction("photo:next");
      break;
    default: break;
  }
}

void recordVoice() {
  show("listening", "full", true);
  const std::string id = voice::recordAndUpload([] { return input.isPowerButtonPhysicallyPressed(); });
  if (id.empty()) {
    show(deck.pages[0], "full", true);
    return;
  }
  voice::waitDone(id);
  show("voice_result", "full", true);
}

std::string status() {
  char buf[400];
  snprintf(buf, sizeof(buf),
           "fw %s (%s%s)\npanel %s\nserver %s (%s)\nwifi %s, %d dBm, %u saved\nframe %s, %u partials\n"
           "battery %d%%%s, %.1f C, %.0f%%, %s\nwakes %u",
           STICKY_FW_VERSION, esp_ota_get_running_partition()->label, ota::onTrial() ? ", on trial" : "",
           display::controller(), settings.server.c_str(), serverOk ? "ok" : "unreachable",
           net::connected() ? "connected" : "off", net::rssi(), static_cast<unsigned>(settings.wifi.size()),
           current.name.c_str(), rtcPartials, telemetry.battery, telemetry.charging ? " charging" : "",
           telemetry.tempC, telemetry.humidity, telemetry.orient, static_cast<unsigned>(rtcWakes));
  return buf;
}

void checkOta(bool force) {
  if (!force && millis() - lastOta < kOtaEveryMs && lastOta != 0) return;
  lastOta = millis();
  const std::string r = ota::checkAndInstall(deck.manifest);
  ESP_LOGI(TAG, "ota: %s", r.c_str());
}

// Talk to the server: deck, then the right frame. Shows a status message when it can't.
void sync(bool firstDraw) {
  if (!net::connect()) {
    serverOk = false;
    if (firstDraw) display::message("Can't join Wi-Fi", settings.wifi.empty()
        ? "No network saved. Connect USB and type: wifi add <name> <password>"
        : "Saved networks are out of range or the password changed.");
    return;
  }
  serverOk = fetchDeck();
  if (!serverOk) {
    if (firstDraw) display::message("Can't reach the Sticky server", settings.server.c_str());
    return;
  }
  const bool startChanged = deck.start == "approve" && current.name != "approve";
  if (deck.chime && !lastChime) hw::chime();  // a new Claude prompt is waiting
  lastChime = deck.chime;
  const std::string target = startChanged ? "approve" : (current.name.empty() ? deck.start : current.name);
  if (!show(target, firstDraw ? "full" : "auto", firstDraw)) serverOk = false;
}
}  // namespace

void setup() {
  ota::bootCheck();  // may roll back to the previous build
  hw::beginEarly();
  Serial.begin(115200);
  rtcWakes++;
  settings.load();
  const bool needWifi = settings.wifi.empty();
  if (needWifi) hw::importCrossmuxWifi();  // SD before the display: they share the SPI bus
  else BoardConfig::releaseSdRail();
  ESP_LOGI(TAG, "Sticky %s, wake %u (%s)", STICKY_FW_VERSION, static_cast<unsigned>(rtcWakes),
           hw::wokeByTimer() ? "timer" : hw::wokeByButton() ? "key" : "power on");
  display::begin();
  input.begin();
  hw::beginSensors();
  hw::readTelemetry();

  console::begin({status, [](const std::string& f) { show(f, "full", true); },
                  [] { return ota::checkAndInstall(deck.manifest); }});

  // A timer wake on battery: only redraw if the server's frame changed, then sleep again.
  if (hw::wokeByTimer() && !hw::onExternalPower()) {
    current.name = rtcFrame;
    current.etag = rtcEtag;
    sync(false);
    if (serverOk && current.pix == nullptr && deck.start == current.name) {
      // 304: the glass still shows the right thing.
      checkOta(false);
      hw::sleepFor(deck.sleepSeconds);
    }
  } else {
    if (rtcWakes == 1) display::message("Starting", "Joining Wi-Fi and fetching your Board.");
    current.name.clear();
    sync(true);
    if (serverOk) checkOta(true);
  }
  lastActivity = lastPoll = millis();
}

void loop() {
  console::poll();
  input.update();
  const uint32_t now = millis();

  // Touch
  if (input.hasTouch() && current.pix) {
    const auto tp = input.getTouchPoint();
    int fx = 0, fy = 0;
    if (tp.valid) toFrame(tp.x, tp.y, fx, fy);
    const Gesture g = gestures.update(input.isTouchPressed() && tp.valid, fx, fy, now);
    if (g.type != GestureType::None) {
      lastActivity = now;
      handleGesture(g);
    }
  }

  // Keys: Up/Down page through the deck; holding the top key records a voice note.
  if (input.wasPressed(InputManager::BTN_UP)) {
    lastActivity = now;
    page(-1);
  }
  if (input.wasPressed(InputManager::BTN_DOWN)) {
    lastActivity = now;
    page(+1);
  }
  if (input.isPowerButtonPressed() && input.getPowerButtonHeldTime() >= 400) {
    lastActivity = now;
    recordVoice();
    lastActivity = millis();
  } else if (input.wasPressed(InputManager::BTN_CONFIRM)) {
    lastActivity = now;
    show(deck.start, "full", true);  // short press: home (or the waiting prompt)
  }

  // Stay current: poll on USB power; on battery, sleep after a quiet minute.
  if (now - lastPoll > (hw::onExternalPower() ? kPollOnUsbMs : 30000) && !gestures.active()) {
    lastPoll = now;
    hw::readTelemetry();
    sync(false);
    checkOta(false);
  }
  if (!hw::onExternalPower() && !gestures.active() && now - lastActivity > kAwakeOnBatteryMs) {
    display::sleep();
    hw::sleepFor(deck.sleepSeconds);
  }
  delay(10);
}

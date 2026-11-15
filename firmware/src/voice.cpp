#include "voice.h"

#include <Arduino.h>
#include <ArduinoJson.h>
#include <Microphone.h>
#include <driver/gpio.h>
#include <esp32-hal-log.h>

#include "net.h"

namespace voice {
namespace {
constexpr const char* TAG = "voice";
constexpr uint32_t kRate = 16000;
constexpr uint32_t kMaxSeconds = 60;
constexpr uint32_t kMinSamples = kRate / 2;  // under half a second is a slip of the finger

void wavHeader(uint8_t* h, uint32_t samples) {
  const uint32_t dataBytes = samples * 2;
  auto put32 = [&](int at, uint32_t v) { for (int i = 0; i < 4; i++) h[at + i] = (v >> (8 * i)) & 0xFF; };
  auto put16 = [&](int at, uint16_t v) { h[at] = v & 0xFF; h[at + 1] = v >> 8; };
  memcpy(h, "RIFF", 4);
  put32(4, 36 + dataBytes);
  memcpy(h + 8, "WAVEfmt ", 8);
  put32(16, 16);
  put16(20, 1);  // PCM
  put16(22, 1);  // mono
  put32(24, kRate);
  put32(28, kRate * 2);
  put16(32, 2);
  put16(34, 16);
  memcpy(h + 36, "data", 4);
  put32(40, dataBytes);
}
}  // namespace

std::string recordAndUpload(const std::function<bool()>& stillHeld) {
  const size_t maxSamples = kRate * kMaxSeconds;
  auto* buf = static_cast<uint8_t*>(ps_malloc(44 + maxSamples * 2));
  if (!buf) return "";
  auto* pcm = reinterpret_cast<int16_t*>(buf + 44);
  gpio_hold_dis(GPIO_NUM_38);  // mic power may still be held low from deep sleep
  freeink::Microphone mic;
  if (!mic.begin(kRate)) {
    ESP_LOGE(TAG, "mic start failed");
    free(buf);
    return "";
  }
  size_t n = 0;
  const uint32_t t0 = millis();
  while (n < maxSamples && (stillHeld() || millis() - t0 < 300)) {
    const int got = mic.read(pcm + n, min<size_t>(1024, maxSamples - n), 100);
    if (got > 0) n += got;
  }
  mic.end();
  ESP_LOGI(TAG, "recorded %.1f s", n / static_cast<float>(kRate));
  if (n < kMinSamples) {
    free(buf);
    return "";
  }
  // The first ~50 ms of PDM output is settling noise.
  const size_t skip = min<size_t>(n / 4, kRate / 20);
  memmove(pcm, pcm + skip, (n - skip) * 2);
  n -= skip;
  wavHeader(buf, n);
  net::Response r = net::postBytes("/api/voice", buf, 44 + n * 2, "audio/wav", 60000);
  free(buf);
  std::string id;
  if (r.status == 200 && r.body) {
    JsonDocument doc;
    if (!deserializeJson(doc, reinterpret_cast<const char*>(r.body))) id = doc["id"] | "";
  }
  net::freeBody(r);
  ESP_LOGI(TAG, "upload -> %s", id.empty() ? "failed" : id.c_str());
  return id;
}

bool waitDone(const std::string& id, uint32_t timeoutMs) {
  const uint32_t t0 = millis();
  while (millis() - t0 < timeoutMs) {
    net::Response r = net::get("/api/voice/" + id, "", 10000);
    std::string status;
    if (r.status == 200 && r.body) {
      JsonDocument doc;
      if (!deserializeJson(doc, reinterpret_cast<const char*>(r.body))) status = doc["status"] | "";
    }
    net::freeBody(r);
    if (status == "done") return true;
    if (status == "error" || status == "failed" || r.status == 404) return false;
    delay(1500);
  }
  return false;
}

}  // namespace voice

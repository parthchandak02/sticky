#include "ota.h"

#include <ArduinoJson.h>
#include <HTTPClient.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp32-hal-log.h>
#include <esp_ota_ops.h>
#include <mbedtls/sha256.h>

#include <cstring>

#include "net.h"
#include "settings.h"

// Same tag format as CrossMux, so either firmware accepts the other's Sticky builds and refuses other boards'.
// Kept in the image on purpose: boardTag() is read at boot so the linker cannot drop it.
extern "C" __attribute__((used)) const char STICKY_BOARD_TAG[] = "CROSSPOINT-BOARD-V1:sticky;";
extern "C" __attribute__((used)) const char* const STICKY_BOARD_TAG_PTR = STICKY_BOARD_TAG;
const char* boardTag() { return *(const char* volatile*)(&STICKY_BOARD_TAG_PTR); }

namespace ota {
namespace {
constexpr const char* TAG = "ota";
constexpr const char* kNs = "sticky-ota";
constexpr int kMaxTrialBoots = 3;

// Finds "CROSSPOINT-BOARD-V1:<name>;" anywhere in a stream.
struct TagScanner {
  static constexpr const char* kMagic = "CROSSPOINT-BOARD-V1:";
  size_t matched = 0;
  bool capturing = false;
  char name[24] = {0};
  size_t len = 0;
  bool found = false, mismatch = false;
  void feed(const uint8_t* d, size_t n) {
    const size_t magicLen = strlen(kMagic);
    for (size_t i = 0; i < n && !mismatch; i++) {
      const char c = static_cast<char>(d[i]);
      if (capturing) {
        if (c == ';') {
          capturing = false;
          name[len] = 0;
          if (strcmp(name, "sticky") == 0) found = true;
          else mismatch = true;
        } else if (len < sizeof(name) - 1 && c > 0x20 && c < 0x7f) {
          name[len++] = c;
        } else {
          capturing = false;
        }
        continue;
      }
      if (c == kMagic[matched]) {
        if (++matched == magicLen) {
          matched = 0;
          capturing = true;
          len = 0;
        }
      } else {
        matched = (c == kMagic[0]) ? 1 : 0;
      }
    }
  }
};
}  // namespace

bool onTrial() {
  Preferences p;
  p.begin(kNs, true);
  const bool trial = p.getBool("trial", false);
  p.end();
  return trial;
}

void bootCheck() {
  ESP_LOGI(TAG, "board tag %s", boardTag() + 20);
  Preferences p;
  p.begin(kNs, false);
  if (!p.getBool("trial", false)) {
    p.end();
    return;
  }
  const int boots = p.getInt("boots", 0) + 1;
  p.putInt("boots", boots);
  const String version = p.getString("version", "");
  const String prev = p.getString("prev", "");
  ESP_LOGW(TAG, "trial boot %d of %d for %s", boots, kMaxTrialBoots, version.c_str());
  if (boots <= kMaxTrialBoots) {
    p.end();
    return;
  }
  // The new build never proved itself: remember it as failed and go back.
  p.putBool("trial", false);
  p.end();
  settings.failedFw = version.c_str();
  settings.save();
  const esp_partition_t* back = esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY,
                                                         prev.length() ? prev.c_str() : nullptr);
  if (back && back != esp_ota_get_running_partition() && esp_ota_set_boot_partition(back) == ESP_OK) {
    ESP_LOGE(TAG, "rolling back to %s", back->label);
    delay(200);
    esp_restart();
  }
  ESP_LOGE(TAG, "rollback target missing, staying on this build");
}

void markGood() {
  Preferences p;
  p.begin(kNs, false);
  if (p.getBool("trial", false)) {
    p.putBool("trial", false);
    p.putInt("boots", 0);
    ESP_LOGI(TAG, "this build is good");
  }
  p.end();
}

std::string checkAndInstall(const std::string& manifestPath) {
  net::Response m = net::get(manifestPath, "", 10000);
  if (m.status == 404) {
    net::freeBody(m);
    return "no manifest";
  }
  if (m.status != 200 || !m.body) {
    net::freeBody(m);
    return "manifest error " + std::to_string(m.status);
  }
  JsonDocument doc;
  const auto err = deserializeJson(doc, reinterpret_cast<const char*>(m.body));
  net::freeBody(m);
  if (err) return "bad manifest";
  const std::string version = doc["version"] | "";
  const std::string file = doc["file"] | "";
  const std::string sha = doc["sha256"] | "";
  const size_t size = doc["size"] | 0;
  if (version.empty() || file.empty() || size == 0) return "incomplete manifest";
  if (version == STICKY_FW_VERSION) return "up to date";
  if (version == settings.failedFw) return "skipping failed " + version;

  const esp_partition_t* target = esp_ota_get_next_update_partition(nullptr);
  if (!target || size > target->size) return "no room";
  ESP_LOGI(TAG, "installing %s (%u bytes) into %s", version.c_str(), static_cast<unsigned>(size), target->label);

  WiFiClient client;
  HTTPClient http;
  http.setTimeout(20000);
  if (!http.begin(client, (settings.server + "/firmware/" + file).c_str())) return "bad url";
  http.addHeader("X-Sticky-Token", settings.token.c_str());
  if (http.GET() != 200) {
    http.end();
    return "download failed";
  }
  esp_ota_handle_t h;
  if (esp_ota_begin(target, size, &h) != ESP_OK) {
    http.end();
    return "ota begin failed";
  }
  mbedtls_sha256_context ctx;
  mbedtls_sha256_init(&ctx);
  mbedtls_sha256_starts(&ctx, 0);
  TagScanner tag;
  static uint8_t buf[4096];
  WiFiClient* s = http.getStreamPtr();
  size_t got = 0;
  uint32_t lastData = millis();
  bool ok = true;
  while (got < size && millis() - lastData < 20000) {
    const size_t avail = s->available();
    if (!avail) {
      if (!http.connected()) break;
      delay(2);
      continue;
    }
    const size_t n = s->readBytes(buf, min(avail, sizeof(buf)));
    lastData = millis();
    mbedtls_sha256_update(&ctx, buf, n);
    tag.feed(buf, n);
    if (esp_ota_write(h, buf, n) != ESP_OK) {
      ok = false;
      break;
    }
    got += n;
  }
  http.end();
  uint8_t digest[32];
  mbedtls_sha256_finish(&ctx, digest);
  mbedtls_sha256_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", digest[i]);

  std::string why;
  if (!ok) why = "write failed";
  else if (got != size) why = "short download";
  else if (sha.size() == 64 && sha != hex) why = "checksum mismatch";
  else if (tag.mismatch || !tag.found) why = "not a Sticky build";
  if (!why.empty()) {
    esp_ota_abort(h);
    settings.failedFw = version;
    settings.save();
    return why;
  }
  if (esp_ota_end(h) != ESP_OK) {  // validates the image structure and its own checksum
    settings.failedFw = version;
    settings.save();
    return "image invalid";
  }
  Preferences p;
  p.begin(kNs, false);
  p.putBool("trial", true);
  p.putInt("boots", 0);
  p.putString("version", version.c_str());
  p.putString("prev", esp_ota_get_running_partition()->label);
  p.end();
  if (esp_ota_set_boot_partition(target) != ESP_OK) return "set boot failed";
  ESP_LOGI(TAG, "installed %s, restarting", version.c_str());
  delay(300);
  esp_restart();
  return "restarting";
}

}  // namespace ota

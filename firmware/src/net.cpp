#include "net.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <esp32-hal-log.h>

#include "settings.h"

Telemetry telemetry;

namespace net {
namespace {
constexpr const char* TAG = "net";

void addHeaders(HTTPClient& http) {
  http.addHeader("X-Sticky-Token", settings.token.c_str());
  http.addHeader("X-Sticky-Fw", STICKY_FW_VERSION);
  if (telemetry.battery >= 0) http.addHeader("X-Sticky-Battery", String(telemetry.battery));
  http.addHeader("X-Sticky-Charging", telemetry.charging ? "1" : "0");
  if (!isnan(telemetry.tempC)) http.addHeader("X-Sticky-Temp", String(telemetry.tempC, 1));
  if (!isnan(telemetry.humidity)) http.addHeader("X-Sticky-Humidity", String(telemetry.humidity, 0));
  http.addHeader("X-Sticky-Rssi", String(WiFi.RSSI()));
  http.addHeader("X-Sticky-Orient", telemetry.orient);
}

Response finish(HTTPClient& http, int code) {
  Response r;
  r.status = code;
  r.etag = http.header("ETag").c_str();
  if (code <= 0 || code == 304) return r;
  WiFiClient* stream = http.getStreamPtr();
  int total = http.getSize();  // -1 when chunked
  size_t cap = total > 0 ? static_cast<size_t>(total) : 64 * 1024;
  r.body = static_cast<uint8_t*>(ps_malloc(cap + 1));
  if (!r.body) {
    r.status = -100;
    return r;
  }
  const uint32_t deadline = millis() + 20000;
  while (http.connected() && (total < 0 || r.len < static_cast<size_t>(total)) && millis() < deadline) {
    size_t avail = stream->available();
    if (!avail) {
      delay(2);
      continue;
    }
    if (r.len + avail > cap) {
      if (total > 0) break;
      cap *= 2;
      auto* grown = static_cast<uint8_t*>(ps_realloc(r.body, cap + 1));
      if (!grown) {
        r.status = -101;
        return r;
      }
      r.body = grown;
    }
    r.len += stream->readBytes(r.body + r.len, avail);
  }
  r.body[r.len] = 0;  // handy for JSON
  if (total > 0 && r.len != static_cast<size_t>(total)) r.status = -102;  // short read
  return r;
}

bool begin(HTTPClient& http, WiFiClient& client, const std::string& path, uint32_t timeoutMs) {
  if (!connected() && !connect()) return false;
  http.setTimeout(timeoutMs);
  http.setConnectTimeout(5000);
  http.setReuse(false);
  const char* keep[] = {"ETag"};
  http.collectHeaders(keep, 1);
  return http.begin(client, (settings.server + path).c_str());
}
}  // namespace

bool connect(uint32_t timeoutMs) {
  if (WiFi.status() == WL_CONNECTED) return true;
  if (settings.wifi.empty()) {
    ESP_LOGW(TAG, "no saved Wi-Fi");
    return false;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);
  const int found = WiFi.scanNetworks(false, false, false, 120);
  // Strongest known network first; fall back to trying each saved one blind (hidden SSIDs).
  std::vector<const WifiNet*> order;
  for (int i = 0; i < found; i++) {
    for (const auto& n : settings.wifi) {
      if (WiFi.SSID(i) == n.ssid.c_str()) order.push_back(&n);
    }
  }
  for (const auto& n : settings.wifi) {
    bool listed = false;
    for (auto* o : order) listed |= (o == &n);
    if (!listed) order.push_back(&n);
  }
  WiFi.scanDelete();
  const uint32_t deadline = millis() + timeoutMs;
  for (auto* n : order) {
    ESP_LOGI(TAG, "joining %s", n->ssid.c_str());
    WiFi.begin(n->ssid.c_str(), n->pass.c_str());
    const uint32_t netDeadline = min(deadline, static_cast<uint32_t>(millis() + 8000));
    while (WiFi.status() != WL_CONNECTED && millis() < netDeadline) delay(50);
    if (WiFi.status() == WL_CONNECTED) {
      ESP_LOGI(TAG, "connected to %s, %s, %d dBm", n->ssid.c_str(), WiFi.localIP().toString().c_str(), WiFi.RSSI());
      return true;
    }
    WiFi.disconnect(false, false);
    if (millis() >= deadline) break;
  }
  ESP_LOGW(TAG, "no network joined");
  return false;
}

bool connected() { return WiFi.status() == WL_CONNECTED; }

void off() {
  WiFi.disconnect(true, false);
  WiFi.mode(WIFI_OFF);
}

int rssi() { return connected() ? WiFi.RSSI() : 0; }

void freeBody(Response& r) {
  free(r.body);
  r.body = nullptr;
  r.len = 0;
}

Response get(const std::string& path, const std::string& etag, uint32_t timeoutMs) {
  WiFiClient client;
  HTTPClient http;
  if (!begin(http, client, path, timeoutMs)) return {-1};
  addHeaders(http);
  if (!etag.empty()) http.addHeader("If-None-Match", etag.c_str());
  Response r = finish(http, http.GET());
  http.end();
  return r;
}

Response postJson(const std::string& path, const std::string& json, uint32_t timeoutMs) {
  WiFiClient client;
  HTTPClient http;
  if (!begin(http, client, path, timeoutMs)) return {-1};
  addHeaders(http);
  http.addHeader("Content-Type", "application/json");
  Response r = finish(http, http.POST(reinterpret_cast<uint8_t*>(const_cast<char*>(json.data())), json.size()));
  http.end();
  return r;
}

Response postBytes(const std::string& path, const uint8_t* data, size_t len, const char* contentType,
                   uint32_t timeoutMs) {
  WiFiClient client;
  HTTPClient http;
  if (!begin(http, client, path, timeoutMs)) return {-1};
  addHeaders(http);
  http.addHeader("Content-Type", contentType);
  Response r = finish(http, http.POST(const_cast<uint8_t*>(data), len));
  http.end();
  return r;
}

}  // namespace net

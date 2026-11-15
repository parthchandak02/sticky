#include "settings.h"

#include <ArduinoJson.h>
#include <Preferences.h>

#ifndef STICKY_SERVER_URL
#define STICKY_SERVER_URL ""
#endif
#ifndef STICKY_TOKEN
#define STICKY_TOKEN ""
#endif

Settings settings;

namespace {
constexpr const char* kNs = "sticky";
constexpr size_t kMaxWifi = 8;
}  // namespace

void Settings::load() {
  Preferences p;
  p.begin(kNs, true);
  server = p.getString("server", STICKY_SERVER_URL).c_str();
  token = p.getString("token", STICKY_TOKEN).c_str();
  chime = p.getBool("chime", true);
  failedFw = p.getString("failed_fw", "").c_str();
  const String json = p.getString("wifi", "[]");
  p.end();

  while (!server.empty() && server.back() == '/') server.pop_back();
  wifi.clear();
  JsonDocument doc;
  if (deserializeJson(doc, json) == DeserializationError::Ok) {
    for (JsonObjectConst n : doc.as<JsonArrayConst>()) {
      wifi.push_back({n["s"] | "", n["p"] | ""});
    }
  }
}

void Settings::save() const {
  JsonDocument doc;
  JsonArray arr = doc.to<JsonArray>();
  for (const auto& n : wifi) {
    JsonObject o = arr.add<JsonObject>();
    o["s"] = n.ssid;
    o["p"] = n.pass;
  }
  String json;
  serializeJson(doc, json);
  Preferences p;
  p.begin(kNs, false);
  p.putString("server", server.c_str());
  p.putString("token", token.c_str());
  p.putBool("chime", chime);
  p.putString("failed_fw", failedFw.c_str());
  p.putString("wifi", json);
  p.end();
}

bool Settings::addWifi(const std::string& ssid, const std::string& pass) {
  if (ssid.empty()) return false;
  removeWifi(ssid);
  if (wifi.size() >= kMaxWifi) wifi.erase(wifi.begin());
  wifi.push_back({ssid, pass});
  return true;
}

bool Settings::removeWifi(const std::string& ssid) {
  for (auto it = wifi.begin(); it != wifi.end(); ++it) {
    if (it->ssid == ssid) {
      wifi.erase(it);
      return true;
    }
  }
  return false;
}

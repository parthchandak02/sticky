// Settings kept in NVS. First boot fills them from build flags and from CrossMux's saved Wi-Fi on the SD card.
#pragma once

#include <Arduino.h>

#include <string>
#include <vector>

struct WifiNet {
  std::string ssid;
  std::string pass;
};

struct Settings {
  std::string server;  // e.g. http://192.168.4.25:8787 (no trailing slash)
  std::string token;
  std::vector<WifiNet> wifi;  // tried strongest first
  bool chime = true;          // the server can still turn chimes off per event
  std::string failedFw;       // a version that failed once is never installed again

  void load();
  void save() const;
  bool addWifi(const std::string& ssid, const std::string& pass);  // replaces an existing ssid
  bool removeWifi(const std::string& ssid);
};

extern Settings settings;

#include "console.h"

#include <Arduino.h>

#include "settings.h"

namespace console {
namespace {
Hooks hooks;
std::string line;

void reply(const std::string& s) { Serial.printf("%s\n", s.c_str()); }

// Splits on spaces; the last argument keeps its spaces (Wi-Fi passwords may contain them).
std::vector<std::string> split(const std::string& s, size_t maxParts) {
  std::vector<std::string> out;
  size_t i = 0;
  while (i < s.size()) {
    while (i < s.size() && s[i] == ' ') i++;
    if (i >= s.size()) break;
    if (out.size() + 1 == maxParts) {
      out.push_back(s.substr(i));
      break;
    }
    size_t j = s.find(' ', i);
    if (j == std::string::npos) j = s.size();
    out.push_back(s.substr(i, j - i));
    i = j;
  }
  return out;
}

void run(const std::string& cmd) {
  auto a = split(cmd, 4);
  if (a.empty()) return;
  const std::string& c = a[0];
  if (c == "help") {
    reply("status | wifi list | wifi add <ssid> <password> | wifi rm <ssid> | server <url> | token <token>");
    reply("chime on|off | show <frame> | ota | reboot");
  } else if (c == "status") {
    reply(hooks.status ? hooks.status() : "?");
  } else if (c == "wifi" && a.size() >= 2 && a[1] == "list") {
    for (const auto& n : settings.wifi) reply("  " + n.ssid);
    if (settings.wifi.empty()) reply("  (none)");
  } else if (c == "wifi" && a.size() >= 3 && a[1] == "add") {
    settings.addWifi(a[2], a.size() >= 4 ? a[3] : "");
    settings.save();
    reply("saved " + a[2]);
  } else if (c == "wifi" && a.size() >= 3 && a[1] == "rm") {
    reply(settings.removeWifi(a[2]) ? "removed" : "not found");
    settings.save();
  } else if (c == "server" && a.size() >= 2) {
    settings.server = a[1];
    while (!settings.server.empty() && settings.server.back() == '/') settings.server.pop_back();
    settings.save();
    reply("server " + settings.server);
  } else if (c == "token" && a.size() >= 2) {
    settings.token = a[1];
    settings.save();
    reply("token saved");
  } else if (c == "chime" && a.size() >= 2) {
    settings.chime = a[1] == "on";
    settings.save();
    reply(settings.chime ? "chime on" : "chime off");
  } else if (c == "show" && a.size() >= 2) {
    if (hooks.show) hooks.show(a[1]);
  } else if (c == "ota") {
    reply(hooks.ota ? hooks.ota() : "?");
  } else if (c == "reboot") {
    reply("rebooting");
    delay(100);
    ESP.restart();
  } else {
    reply("unknown command, try help");
  }
}
}  // namespace

void begin(const Hooks& h) { hooks = h; }

void poll() {
  while (Serial.available()) {
    const char ch = static_cast<char>(Serial.read());
    if (ch == '\r') continue;
    if (ch == '\n') {
      std::string cmd = line;
      line.clear();
      run(cmd);
    } else if (line.size() < 200) {
      line += ch;
    }
  }
}

}  // namespace console

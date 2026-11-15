// Serial console (115200): setup and diagnostics over USB.
//   status | wifi list | wifi add <ssid> <password> | wifi rm <ssid> | server <url> | token <token>
//   chime on|off | show <frame> | ota | reboot | help
#pragma once

#include <functional>
#include <string>

namespace console {

struct Hooks {
  std::function<std::string()> status;
  std::function<void(const std::string& frame)> show;
  std::function<std::string()> ota;
};

void begin(const Hooks& hooks);
void poll();  // call from loop()

}  // namespace console

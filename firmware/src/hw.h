// Board services: power latch, battery, room sensor, orientation, buzzer, deep sleep, CrossMux Wi-Fi import.
#pragma once

#include <Arduino.h>

namespace hw {

void beginEarly();   // first thing in setup(): power latch, SD rail
void beginSensors();  // gauge, SHT40, IMU, buzzer
void readTelemetry();  // fills ::telemetry (battery, charging, temperature, humidity, orientation)
bool onExternalPower();  // best guess: charging, or full and not discharging
void chime();          // two short notes
// Deep sleep until a button or the timer. Never returns.
[[noreturn]] void sleepFor(uint32_t seconds);
bool wokeByTimer();
bool wokeByButton();
// Copy Wi-Fi networks saved by CrossMux on the SD card into our settings. Returns how many.
int importCrossmuxWifi();

}  // namespace hw

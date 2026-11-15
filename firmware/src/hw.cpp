#include "hw.h"

#include <ArduinoJson.h>
#include <BatteryMonitor.h>
#include <BoardConfig.h>
#include <Buzzer.h>
#include <EnvironmentSensor.h>
#include <Imu.h>
#include <PowerManager.h>
#include <SDCardManager.h>
#include <driver/gpio.h>
#include <esp32-hal-log.h>
#include <esp_mac.h>
#include <esp_sleep.h>
#include <mbedtls/base64.h>

#include "net.h"
#include "settings.h"

namespace hw {
namespace {
constexpr const char* TAG = "hw";
constexpr int PIN_CHARGE_STATE = 40;  // LOW while charging
BatteryMonitor battery;
freeink::Buzzer buzzer;
freeink::EnvironmentSensor env;
freeink::Imu imu;
bool envOk = false, imuOk = false, buzzerOk = false;
int16_t lastCurrentSign = 0;
}  // namespace

void beginEarly() {
  BoardConfig::holdPowerRails();
  pinMode(PIN_CHARGE_STATE, INPUT_PULLUP);
}

void beginSensors() {
  envOk = env.begin();
  imuOk = imu.begin();
  buzzerOk = buzzer.begin();
  ESP_LOGI(TAG, "sensors: sht40 %s, imu %s", envOk ? "ok" : "missing", imuOk ? "ok" : "missing");
}

void readTelemetry() {
  const auto st = battery.readStatus();
  if (st.percentageKnown) telemetry.battery = st.percentage;
  telemetry.charging = (st.chargingKnown && st.charging) || digitalRead(PIN_CHARGE_STATE) == LOW;
  float t, rh;
  if (envOk && env.read(t, rh)) {
    telemetry.tempC = t;
    telemetry.humidity = rh;
  }
  if (imuOk) {
    freeink::Imu::Sample s;
    if (imu.read(s)) telemetry.orient = fabsf(s.ay) > fabsf(s.ax) + 0.3f ? "portrait" : "landscape";
  }
}

bool onExternalPower() {
  if (telemetry.charging) return true;
  // Full battery on a charger: the gauge reads 100% and the charger has stopped. Treat as plugged in.
  return telemetry.battery >= 99;
}

void chime() {
  if (!buzzerOk || !settings.chime) return;
  buzzer.tone(1568, 70);
  delay(110);
  buzzer.tone(2093, 90);
  delay(120);
  buzzer.noTone();
}

void sleepFor(uint32_t seconds) {
  ESP_LOGI(TAG, "sleeping %us", static_cast<unsigned>(seconds));
  net::off();
  // Keep the power latch high through deep sleep, or the board switches itself off.
  gpio_hold_en(GPIO_NUM_45);
  gpio_hold_en(GPIO_NUM_46);
  freeink::PowerManager::powerDownRailsForSleep();
  freeink::PowerManager::waitForPowerButtonRelease();
  freeink::PowerManager::armWakeOnPins((1ULL << 4) | (1ULL << 5) | (1ULL << 6), true);
  esp_sleep_enable_timer_wakeup(static_cast<uint64_t>(seconds) * 1000000ULL);
  Serial.flush();
  freeink::PowerManager::deepSleep();
  esp_deep_sleep_start();  // not reached
}

bool wokeByTimer() { return esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_TIMER; }
bool wokeByButton() { return esp_sleep_get_wakeup_cause() == ESP_SLEEP_WAKEUP_EXT1; }

int importCrossmuxWifi() {
  if (!SdMan.begin()) {
    ESP_LOGW(TAG, "no SD card");
    return 0;
  }
  const String text = SdMan.readFile("/.crosspoint/wifi.json");
  SdMan.shutdown();
  if (text.isEmpty()) return 0;
  JsonDocument doc;
  if (deserializeJson(doc, text)) return 0;
  uint8_t key[6] = {0};
  esp_efuse_mac_get_default(key);  // CrossMux XORs passwords with the factory MAC
  int added = 0;
  for (JsonObjectConst n : doc["credentials"].as<JsonArrayConst>()) {
    const char* ssid = n["ssid"] | "";
    const char* obf = n["password_obf"] | "";
    std::string pass;
    if (*obf) {
      size_t outLen = 0;
      unsigned char buf[128];
      if (mbedtls_base64_decode(buf, sizeof(buf), &outLen, reinterpret_cast<const unsigned char*>(obf), strlen(obf)) == 0) {
        for (size_t i = 0; i < outLen; i++) buf[i] ^= key[i % 6];
        pass.assign(reinterpret_cast<char*>(buf), outLen);
      }
    } else {
      pass = n["password"] | "";  // older plain files
    }
    if (*ssid && settings.addWifi(ssid, pass)) added++;
  }
  if (added) settings.save();
  ESP_LOGI(TAG, "imported %d Wi-Fi network(s) from CrossMux", added);
  return added;
}

}  // namespace hw

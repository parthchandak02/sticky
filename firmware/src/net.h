// Wi-Fi and HTTP to sticky-server. Every request carries the token, the firmware version and telemetry.
#pragma once

#include <Arduino.h>

#include <string>

struct Telemetry {
  int battery = -1;  // percent, -1 unknown
  bool charging = false;
  float tempC = NAN;
  float humidity = NAN;
  const char* orient = "landscape";
};

extern Telemetry telemetry;

namespace net {

// Connect to the strongest saved network. Returns true when connected (waits up to timeoutMs).
bool connect(uint32_t timeoutMs = 15000);
bool connected();
void off();
int rssi();

struct Response {
  int status = 0;        // HTTP status, or <0 for a transport error
  uint8_t* body = nullptr;  // PSRAM, owned by the caller (free with net::freeBody)
  size_t len = 0;
  std::string etag;
};
void freeBody(Response& r);

// GET path (relative to the server). etag: send If-None-Match; a 304 has status 304 and no body.
Response get(const std::string& path, const std::string& etag = "", uint32_t timeoutMs = 15000);
// POST a JSON body; the response body is returned like get().
Response postJson(const std::string& path, const std::string& json, uint32_t timeoutMs = 15000);
// POST raw bytes (voice upload).
Response postBytes(const std::string& path, const uint8_t* data, size_t len, const char* contentType,
                   uint32_t timeoutMs = 60000);

}  // namespace net

// A screen from the server: a 4-level image plus its touch map.
#pragma once

#include <Arduino.h>

#include <string>
#include <vector>

struct Hotspot {
  bool hold = false;
  std::string action;
  int16_t x = 0, y = 0, w = 0, h = 0;
  bool contains(int px, int py) const { return px >= x && px < x + w && py >= y && py < y + h; }
};

struct Frame {
  std::string name;
  uint16_t w = 0, h = 0;      // 800x480 landscape or 480x800 portrait, in frame pixels
  uint8_t* pix = nullptr;     // PSRAM, w*h/4 bytes, 2 bits per pixel, MSB first, top row first, 0=black 3=white
  std::string etag;
  std::vector<Hotspot> hotspots;

  ~Frame() { release(); }
  void release();
  uint8_t level(int x, int y) const { return (pix[(y * w + x) >> 2] >> (6 - 2 * (x & 3))) & 3; }
  // Smallest hotspot under a point, preferring the requested kind (nullptr if none).
  const Hotspot* hit(int x, int y, bool wantHold) const;
};

// Decode the server's 2-bit BMP (bottom-up rows, palette black..white). Returns false on a bad file.
bool decodeBmp2(const uint8_t* data, size_t len, Frame& out);
// Parse {"hotspots":[{kind,action,x,y,w,h}]}.
bool parseHotspots(const char* json, Frame& out);

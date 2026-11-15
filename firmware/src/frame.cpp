#include "frame.h"

#include <ArduinoJson.h>

namespace {
uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | (static_cast<uint32_t>(p[3]) << 24); }
uint16_t le16(const uint8_t* p) { return p[0] | (p[1] << 8); }
}  // namespace

void Frame::release() {
  free(pix);
  pix = nullptr;
}

const Hotspot* Frame::hit(int x, int y, bool wantHold) const {
  const Hotspot* best = nullptr;
  for (int pass = 0; pass < 2 && !best; pass++) {
    for (const auto& h : hotspots) {
      if (!h.contains(x, y)) continue;
      if (pass == 0 && h.hold != wantHold) continue;
      if (!best || h.w * h.h < best->w * best->h) best = &h;
    }
  }
  return best;
}

bool decodeBmp2(const uint8_t* d, size_t len, Frame& out) {
  if (len < 54 || d[0] != 'B' || d[1] != 'M') return false;
  const uint32_t offset = le32(d + 10);
  const int32_t w = static_cast<int32_t>(le32(d + 18));
  const int32_t hRaw = static_cast<int32_t>(le32(d + 22));
  const uint16_t bpp = le16(d + 28);
  if (bpp != 2 || w <= 0 || w > 800 || hRaw == 0 || abs(hRaw) > 800) return false;
  const bool bottomUp = hRaw > 0;
  const int h = abs(hRaw);
  // Palette order is black..white from our server; map through it anyway so a reordered palette still works.
  uint8_t map[4] = {0, 1, 2, 3};
  const uint32_t dibSize = le32(d + 14);
  const uint8_t* pal = d + 14 + dibSize;
  if (pal + 16 <= d + offset) {
    for (int i = 0; i < 4; i++) map[i] = static_cast<uint8_t>(pal[i * 4] / 85 > 3 ? 3 : pal[i * 4] / 85);
  }
  const size_t rowBytes = ((w * 2 + 31) / 32) * 4;
  if (offset + rowBytes * h > len) return false;
  out.release();
  out.w = w;
  out.h = h;
  out.pix = static_cast<uint8_t*>(ps_calloc(w * h / 4 + 1, 1));
  if (!out.pix) return false;
  for (int y = 0; y < h; y++) {
    const uint8_t* src = d + offset + rowBytes * (bottomUp ? (h - 1 - y) : y);
    for (int x = 0; x < w; x++) {
      const uint8_t v = map[(src[x >> 2] >> (6 - 2 * (x & 3))) & 3];
      out.pix[(y * w + x) >> 2] |= v << (6 - 2 * (x & 3));
    }
  }
  return true;
}

bool parseHotspots(const char* json, Frame& out) {
  JsonDocument doc;
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;
  out.hotspots.clear();
  for (JsonObjectConst o : doc["hotspots"].as<JsonArrayConst>()) {
    Hotspot h;
    h.hold = strcmp(o["kind"] | "tap", "hold") == 0;
    h.action = o["action"] | "";
    h.x = o["x"] | 0;
    h.y = o["y"] | 0;
    h.w = o["w"] | 0;
    h.h = o["h"] | 0;
    if (!h.action.empty() && h.w > 0 && h.h > 0) out.hotspots.push_back(h);
  }
  return true;
}

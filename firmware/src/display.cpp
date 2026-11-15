#include "display.h"

#include <BoardConfig.h>
#include <EInkDisplay.h>
#include <esp32-hal-log.h>

#include <cmath>

#include "font.h"

namespace display {
namespace {
constexpr const char* TAG = "display";
constexpr int W = 800, H = 480, ROW = W / 8, PLANE = ROW * H;

EInkDisplay epd(0, 0, 0, 0, 0, 0);  // pins come from the Sticky board profile
uint8_t* base = nullptr;  // the frame as black/white (1 = white), kept to restore regions
uint8_t* lsb = nullptr;
uint8_t* msb = nullptr;

// Frame pixel -> panel pixel. Portrait frames (480x800) are shown with the device turned
// a quarter to the left: frame (x, y) lands on panel (y, 479 - x).
inline void toPanel(const Frame& f, int x, int y, int& px, int& py) {
  if (f.w == W) {
    px = x;
    py = y;
  } else {
    px = y;
    py = H - 1 - x;
  }
}

inline void setBit(uint8_t* plane, int x, int y, bool on) {
  uint8_t& b = plane[y * ROW + (x >> 3)];
  const uint8_t m = 0x80 >> (x & 7);
  b = on ? (b | m) : (b & ~m);
}

inline void fbPixel(int x, int y, bool white) {
  if (x < 0 || y < 0 || x >= W || y >= H) return;
  setBit(epd.getFrameBuffer(), x, y, white);
}

// Build the overlay planes from a frame: base is black wherever the pixel is not white,
// the masks then lighten dark gray (both bits) and light gray (MSB only).
void buildPlanes(const Frame& f) {
  memset(base, 0x00, PLANE);
  memset(lsb, 0x00, PLANE);
  memset(msb, 0x00, PLANE);
  for (int y = 0; y < f.h; y++) {
    for (int x = 0; x < f.w; x++) {
      const uint8_t lv = f.level(x, y);
      int px, py;
      toPanel(f, x, y, px, py);
      if (lv == 3) setBit(base, px, py, true);
      if (lv == 1) setBit(lsb, px, py, true);
      if (lv == 1 || lv == 2) setBit(msb, px, py, true);
    }
  }
}

void window(int x, int y, int w, int h) {
  int x0 = max(0, x) & ~7, x1 = min(W, (x + w + 7) & ~7);
  int y0 = max(0, y), y1 = min(H, y + h);
  if (x1 > x0 && y1 > y0) epd.displayWindow(x0, y0, x1 - x0, y1 - y0);
}

int textWidth(const Font& font, const char* s) {
  int w = 0;
  for (; *s; s++) {
    const unsigned c = static_cast<unsigned char>(*s);
    if (c >= 32 && c < 127) w += font.glyphs[c - 32].adv;
  }
  return w;
}

void drawText(const Font& font, int x, int y, const char* s) {
  for (; *s; s++) {
    const unsigned c = static_cast<unsigned char>(*s);
    if (c < 32 || c >= 127) continue;
    const FontGlyph& g = font.glyphs[c - 32];
    const int rowBytes = (g.w + 7) / 8;
    for (int gy = 0; gy < font.height; gy++) {
      const uint8_t* row = font.data + g.offset + gy * rowBytes;
      for (int gx = 0; gx < g.w; gx++) {
        if (row[gx >> 3] & (1 << (gx & 7))) fbPixel(x + gx, y + gy, false);
      }
    }
    x += g.adv;
  }
}

// Word-wrap into lines no wider than maxW; draws them and returns the height used.
int drawWrapped(const Font& font, int x, int y, int maxW, const char* text) {
  char line[96];
  int used = 0;
  const char* p = text;
  while (*p) {
    int len = 0, lastSpace = -1;
    while (p[len] && p[len] != '\n' && len < 95) {
      line[len] = p[len];
      line[len + 1] = 0;
      if (p[len] == ' ') lastSpace = len;
      if (textWidth(font, line) > maxW && lastSpace > 0) {
        len = lastSpace;
        break;
      }
      len++;
    }
    line[len] = 0;
    drawText(font, x, y + used, line);
    used += font.height + 6;
    p += len;
    while (*p == ' ' || *p == '\n') p++;
  }
  return used;
}
}  // namespace

void begin() {
  epd.begin();
  if (!base) {
    base = static_cast<uint8_t*>(ps_malloc(PLANE));
    lsb = static_cast<uint8_t*>(ps_malloc(PLANE));
    msb = static_cast<uint8_t*>(ps_malloc(PLANE));
  }
  ESP_LOGI(TAG, "panel %s", epd.getControllerName());
}

const char* controller() { return epd.getControllerName(); }

void showFrame(const Frame& f, bool full) {
  if (!f.pix) return;
  buildPlanes(f);
  bool hasGray = false;
  for (int i = 0; i < PLANE && !hasGray; i++) hasGray = msb[i] != 0;
  epd.setFramebuffer(base);
  if (full) {
    epd.displayBuffer(EInkDisplay::FULL_REFRESH);  // clean slate: both RAM planes rewritten
  }
  if (hasGray) {
    epd.displayGrayscaleBase(freeink::GrayscaleMode::Overlay, EInkDisplay::FAST_REFRESH);
    epd.copyGrayscaleBuffers(lsb, msb);
    epd.displayGrayBuffer();
    epd.cleanupGrayscaleBuffers(base);  // back to black/white bookkeeping, gray pixels stay on the glass
  } else if (!full) {
    epd.displayBuffer(EInkDisplay::FAST_REFRESH);
  }
}

void ring(const Frame& f, int cx, int cy, int r, float progress) {
  int pcx, pcy;
  toPanel(f, cx, cy, pcx, pcy);
  const int thick = 7;
  for (int dy = -r - thick; dy <= r + thick; dy++) {
    for (int dx = -r - thick; dx <= r + thick; dx++) {
      const float d = sqrtf(dx * dx + dy * dy);
      if (d < r || d > r + thick) continue;
      float a = atan2f(dx, -dy);  // 0 at 12 o'clock, clockwise
      if (a < 0) a += 2 * PI;
      if (a / (2 * PI) <= progress) fbPixel(pcx + dx, pcy + dy, false);
    }
  }
  window(pcx - r - thick, pcy - r - thick, 2 * (r + thick) + 1, 2 * (r + thick) + 1);
}

void restore(const Frame& f, int x, int y, int w, int h) {
  int ax, ay, bx, by;
  toPanel(f, x, y, ax, ay);
  toPanel(f, x + w - 1, y + h - 1, bx, by);
  const int x0 = max(0, min(ax, bx)), x1 = min(W - 1, max(ax, bx));
  const int y0 = max(0, min(ay, by)), y1 = min(H - 1, max(ay, by));
  uint8_t* fb = epd.getFrameBuffer();
  for (int yy = y0; yy <= y1; yy++) {
    for (int xx = x0; xx <= x1; xx++) {
      const bool white = base[yy * ROW + (xx >> 3)] & (0x80 >> (xx & 7));
      setBit(fb, xx, yy, white);
    }
  }
  window(x0, y0, x1 - x0 + 1, y1 - y0 + 1);
}

void tapMark(const Frame& f, int x, int y) {
  int px, py;
  toPanel(f, x, y, px, py);
  for (int dy = -5; dy <= 5; dy++)
    for (int dx = -5; dx <= 5; dx++)
      if (dx * dx + dy * dy <= 25) fbPixel(px + dx, py + dy, false);
  window(px - 8, py - 6, 16, 12);
}

void message(const char* title, const char* detail) {
  uint8_t* fb = epd.getFrameBuffer();
  memset(fb, 0xFF, PLANE);
  for (int y = 40; y < 42; y++)
    for (int x = 24; x < W - 24; x++) fbPixel(x, y, false);
  const int used = drawWrapped(FONT_BIG, 24, 72, W - 48, title);
  if (detail) drawWrapped(FONT_SMALL, 24, 72 + used + 12, W - 48, detail);
  drawText(FONT_SMALL, 24, H - 24 - FONT_SMALL.height, "Sticky");
  epd.displayBuffer(EInkDisplay::FULL_REFRESH);
  memcpy(base, fb, PLANE);
}

void sleep() { epd.deepSleep(); }

}  // namespace display

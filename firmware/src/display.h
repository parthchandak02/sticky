// The panel: server frames in 4 grays, quick 1-bit partial updates on top, and plain status messages.
#pragma once

#include <Arduino.h>

#include "frame.h"

namespace display {

void begin();
const char* controller();  // "SSD1677" or "SSD2677"

// Show a server frame. full=true forces a clean full refresh (clears ghosting).
// Gray frames are drawn in overlay mode, so partial updates (rings, marks) stay flash-free afterwards.
void showFrame(const Frame& f, bool full);

// Hold feedback: a ring around (cx, cy) in frame pixels, filled to progress 0..1. Partial refresh.
void ring(const Frame& f, int cx, int cy, int r, float progress);
// Put a region of the current frame back the way the server drew it (after a cancelled hold).
void restore(const Frame& f, int x, int y, int w, int h);
// A small black mark under a tapped control, so a tap feels instant while the next frame loads.
void tapMark(const Frame& f, int x, int y);

// A full-screen status message from the device itself (no Wi-Fi, no server, updating).
void message(const char* title, const char* detail = nullptr);

void sleep();  // panel deep sleep; begin() again after wake

}  // namespace display

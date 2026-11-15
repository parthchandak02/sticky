// Turns raw touch samples (in frame pixels) into tap, hold and swipe gestures.
#pragma once

#include <Arduino.h>

enum class GestureType { None, Down, HoldProgress, HoldDone, HoldCancel, Tap, SwipeLeft, SwipeRight, SwipeUp, SwipeDown };

struct Gesture {
  GestureType type = GestureType::None;
  int x = 0, y = 0;     // where the finger went down
  float progress = 0;   // HoldProgress: 0..1
};

class GestureReader {
 public:
  uint32_t holdMs = 1000;    // the server can change this
  int swipeMin = 60;         // pixels
  int moveSlop = 18;         // a tap or hold may wander this far

  // Feed one sample per loop: touching + position. holdArmed: the finger went down on a hold target.
  Gesture update(bool touching, int x, int y, uint32_t now);
  void armHold(bool armed) { holdArmed_ = armed; }
  bool active() const { return down_; }

 private:
  bool down_ = false, moved_ = false, holdArmed_ = false, holdDone_ = false;
  int x0_ = 0, y0_ = 0, lx_ = 0, ly_ = 0;
  uint32_t t0_ = 0;
  float lastProgress_ = 0;
};

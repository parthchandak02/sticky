#include "gesture.h"

Gesture GestureReader::update(bool touching, int x, int y, uint32_t now) {
  Gesture g;
  if (touching && !down_) {
    down_ = true;
    moved_ = holdDone_ = false;
    x0_ = lx_ = x;
    y0_ = ly_ = y;
    t0_ = now;
    lastProgress_ = 0;
    g.type = GestureType::Down;
    g.x = x;
    g.y = y;
    return g;
  }
  if (touching && down_) {
    lx_ = x;
    ly_ = y;
    if (abs(x - x0_) > moveSlop || abs(y - y0_) > moveSlop) {
      if (holdArmed_ && !moved_ && !holdDone_ && lastProgress_ > 0) {
        moved_ = true;
        g.type = GestureType::HoldCancel;
        g.x = x0_;
        g.y = y0_;
        return g;
      }
      moved_ = true;
    }
    if (holdArmed_ && !moved_ && !holdDone_) {
      const float p = min(1.0f, static_cast<float>(now - t0_) / holdMs);
      if (p >= 1.0f) {
        holdDone_ = true;
        g.type = GestureType::HoldDone;
      } else if (p - lastProgress_ >= 0.25f) {  // a few steps: each one is a partial refresh
        lastProgress_ = p;
        g.type = GestureType::HoldProgress;
        g.progress = p;
      }
      g.x = x0_;
      g.y = y0_;
    }
    return g;
  }
  if (!touching && down_) {
    down_ = false;
    g.x = x0_;
    g.y = y0_;
    if (holdDone_) return g;  // already reported
    const int dx = lx_ - x0_, dy = ly_ - y0_;
    if (abs(dx) >= swipeMin || abs(dy) >= swipeMin) {
      if (abs(dx) > abs(dy)) g.type = dx < 0 ? GestureType::SwipeLeft : GestureType::SwipeRight;
      else g.type = dy < 0 ? GestureType::SwipeUp : GestureType::SwipeDown;
    } else if (holdArmed_ && lastProgress_ > 0) {
      g.type = GestureType::HoldCancel;  // let go early: nothing happens
    } else if (!moved_) {
      g.type = GestureType::Tap;
    }
    holdArmed_ = false;
  }
  return g;
}

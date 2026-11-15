"""Render Sticky screens: Jinja template + data -> headless Chromium -> the panel's 4 gray levels.

The same templates feed the demo renders (scripts/render_screens.py) and the live server. A render
returns the image and the hotspots (every element with data-tap / data-hold) that the device maps
touches to. Chromium runs in one dedicated thread; results are cached by their inputs, so a device
polling an unchanged screen costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from .config import REPO_ROOT

SCREENS = REPO_ROOT / "screens"
TEMPLATES = SCREENS / "templates"
LIVE_HTML = SCREENS / "out" / "html"  # same depth as the demo pages, so relative CSS and font paths work
LIVE_IMG = SCREENS / "out" / "img"
LEVELS = (0, 85, 170, 255)
_SNAP = [min(LEVELS, key=lambda lv, v=v: abs(lv - v)) for v in range(256)]

HOTSPOT_JS = """() => [...document.querySelectorAll('[data-tap],[data-hold]')].map((el) => {
  const r = el.getBoundingClientRect();
  return { kind: el.dataset.hold ? 'hold' : 'tap', action: el.dataset.hold || el.dataset.tap,
           x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) };
})"""


def environment() -> Environment:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    env.filters.update(cos=math.cos, sin=math.sin)
    return env


def snap(img: Image.Image) -> Image.Image:
    """Nearest of the 4 levels: anti-aliased edges become the panel's own grays."""
    return img.convert("L").point(_SNAP)


def _palette() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat = [c for v in LEVELS for c in (v, v, v)]
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return pal


def dither_photo(src: Path, dst: Path, size: tuple[int, int], gamma: float = 0.85, contrast: float = 1.0,
                 center: tuple[float, float] = (0.5, 0.4), zoom: float = 1.0) -> None:
    """Crop to size, tone-map for paper (lift shadows, keep highlights off pure white),
    soften a touch so the dither reads as grain, then error-diffuse to the 4 panel levels."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("L")
    if zoom > 1:
        w, h = im.size
        cw, ch = int(w / zoom), int(h / zoom)
        cx, cy = int((w - cw) * center[0]), int((h - ch) * center[1])
        im = im.crop((cx, cy, cx + cw, cy + ch))
    im = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=center)
    im = ImageOps.autocontrast(im, cutoff=0.5)
    im = im.point(lambda v: int(16 + 200 * ((v / 255) ** gamma)))
    im = ImageEnhance.Contrast(im).enhance(contrast)
    im = im.filter(ImageFilter.GaussianBlur(0.5))
    q = im.convert("RGB").quantize(palette=_palette(), dither=Image.Dither.FLOYDSTEINBERG)
    dst.parent.mkdir(parents=True, exist_ok=True)
    q.convert("L").save(dst)


def _chromium_path() -> str | None:
    """Playwright's own browser if installed, else a Chromium already on the machine."""
    if os.environ.get("STICKY_CHROMIUM"):
        return os.environ["STICKY_CHROMIUM"]
    for root in ("/opt/ms-playwright", "/opt/pw-browsers"):
        base = Path(root)
        if not base.is_dir():
            continue
        for d in sorted(base.glob("chromium-*"), reverse=True):
            for sub in ("chrome-linux64/chrome", "chrome-linux/chrome",
                        "chrome-mac/Chromium.app/Contents/MacOS/Chromium"):
                if (d / sub).exists():
                    return str(d / sub)
    return None


class Renderer:
    def __init__(self, cache_size: int = 48):
        self.env = environment()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sticky-render")
        self._browser = None
        self._pw = None
        self._cache: OrderedDict[str, tuple[Image.Image, list[dict]]] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        LIVE_HTML.mkdir(parents=True, exist_ok=True)

    # Runs only on the render thread.
    def _browser_once(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._pw = sync_playwright().start()
            try:
                self._browser = self._pw.chromium.launch()
            except Exception:
                exe = _chromium_path()
                if not exe:
                    raise
                self._browser = self._pw.chromium.launch(executable_path=exe)
        return self._browser

    def _shoot(self, html: str, name: str, w: int, h: int) -> tuple[Image.Image, list[dict]]:
        page_file = LIVE_HTML / f"live-{name}.html"
        page_file.write_text(html)
        page = self._browser_once().new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
        try:
            page.goto(page_file.as_uri())
            page.evaluate("() => document.fonts.ready")
            page.wait_for_timeout(60)
            png = page.screenshot(type="png")
            hotspots = page.evaluate(HOTSPOT_JS)
        finally:
            page.close()
        import io

        return snap(Image.open(io.BytesIO(png))), hotspots

    def render(self, template: str, name: str, ctx: dict[str, Any], portrait: bool = False
               ) -> tuple[Image.Image, list[dict]]:
        w, h = (480, 800) if portrait else (800, 480)
        html = self.env.get_template(template + ".html.j2").render(w=w, h=h, frame=name, **ctx)
        key = hashlib.sha256(f"{name}|{w}x{h}|{html}".encode()).hexdigest()
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        result = self._pool.submit(self._shoot, html, name, w, h).result(timeout=30)
        with self._lock:
            self._cache[key] = result
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return result

    def close(self) -> None:
        def _stop():
            if self._browser:
                self._browser.close()
            if self._pw:
                self._pw.stop()
        self._pool.submit(_stop).result(timeout=10)


def hotspots_json(hotspots: list[dict], frame: str, extra: dict[str, Any] | None = None) -> str:
    return json.dumps({"frame": frame, "hotspots": hotspots, **(extra or {})})

"""Drawing helpers for a 4-level grayscale e-paper panel (800x480)."""

from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from ..config import ASSETS

W, H = 800, 480
BLACK, DARK, LIGHT, WHITE = 0, 85, 170, 255
LEVELS = (BLACK, DARK, LIGHT, WHITE)

FONT_FILES = {
    "regular": "Inter-400.ttf",
    "semibold": "Inter-600.ttf",
    "bold": "Inter-700.ttf",
    "mono": "JetBrainsMono-500.ttf",
}


@lru_cache(maxsize=64)
def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(ASSETS / "fonts" / FONT_FILES[weight]), size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("L", (W, H), WHITE)
    return img, ImageDraw.Draw(img)


def text_w(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont) -> int:
    return int(d.textlength(text, font=f))


def fit(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int) -> str:
    """Trim text with an ellipsis so it fits in width."""
    if text_w(d, text, f) <= width:
        return text
    while text and text_w(d, text + "...", f) > width:
        text = text[:-1]
    return text.rstrip() + "..."


def wrap(d: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if text_w(d, trial, f) <= width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        cur = w
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = fit(d, lines[-1] + " ...", f, width)
    return lines


def header(d: ImageDraw.ImageDraw, title: str, right: str) -> None:
    d.rectangle([0, 0, W, 44], fill=BLACK)
    d.text((20, 22), title, font=font(20, "bold"), fill=WHITE, anchor="lm")
    d.text((W - 20, 22), right, font=font(18, "semibold"), fill=WHITE, anchor="rm")


def label(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: int = DARK) -> None:
    d.text(xy, text.upper(), font=font(13, "bold"), fill=fill)


def bar(d: ImageDraw.ImageDraw, box: tuple[int, int, int, int], frac: float, fill: int = BLACK) -> None:
    x0, y0, x1, y1 = box
    d.rectangle(box, outline=BLACK, width=2)
    frac = max(0.0, min(1.0, frac))
    if frac > 0:
        d.rectangle([x0 + 3, y0 + 3, x0 + 3 + int((x1 - x0 - 6) * frac), y1 - 3], fill=fill)


def footer(d: ImageDraw.ImageDraw, text: str, page: int, pages: int) -> None:
    d.line([20, H - 26, W - 20, H - 26], fill=LIGHT, width=1)
    d.text((20, H - 13), text, font=font(12), fill=DARK, anchor="lm")
    dots_x = W - 20 - (pages - 1) * 14
    for i in range(pages):
        cx = dots_x + i * 14
        d.ellipse([cx - 4, H - 17, cx + 4, H - 9], fill=BLACK if i == page else None, outline=BLACK)


def quantize(img: Image.Image) -> Image.Image:
    """Snap every pixel to the panel's four gray levels (no dithering, keeps text crisp)."""
    lut = [min(LEVELS, key=lambda lv: abs(lv - v)) for v in range(256)]
    return img.point(lut)


def to_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def to_bmp(img: Image.Image, rotate: int = 0, bits: int = 8) -> bytes:
    """Grayscale BMP. bits=8 is a plain palette BMP; bits=2 packs the four panel levels
    (index 0 black .. 3 white), a quarter of the size and native to CrossPoint-family firmware."""
    out = img.rotate(rotate, expand=True) if rotate else img
    if bits == 8:
        buf = io.BytesIO()
        out.convert("L").save(buf, "BMP")
        return buf.getvalue()
    if bits != 2:
        raise ValueError("bits must be 2 or 8")
    q = quantize(out.convert("L"))
    w, h = q.size
    row_bytes = (w * 2 + 31) // 32 * 4
    index = {lv: i for i, lv in enumerate(LEVELS)}
    px = q.load()
    rows = bytearray()
    for y in range(h - 1, -1, -1):  # BMP rows are bottom-up
        row = bytearray(row_bytes)
        for x in range(w):
            row[x >> 2] |= index[px[x, y]] << (6 - 2 * (x & 3))
        rows += row
    palette = b"".join(bytes((lv, lv, lv, 0)) for lv in LEVELS)
    offset = 14 + 40 + len(palette)
    header = b"BM" + (offset + len(rows)).to_bytes(4, "little") + b"\0\0\0\0" + offset.to_bytes(4, "little")
    dib = (
        (40).to_bytes(4, "little") + w.to_bytes(4, "little", signed=True) + h.to_bytes(4, "little", signed=True)
        + (1).to_bytes(2, "little") + (2).to_bytes(2, "little") + (0).to_bytes(4, "little")
        + len(rows).to_bytes(4, "little") + (2835).to_bytes(4, "little") * 2
        + (4).to_bytes(4, "little") + (4).to_bytes(4, "little")
    )
    return header + dib + palette + bytes(rows)


def money(v: float) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}"


def tokens(v: float) -> str:
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if v >= div:
            return f"{v / div:.1f}{unit}"
    return f"{v:.0f}"


def ago(seconds: float) -> str:
    s = int(max(0, seconds))
    if s < 60:
        return "now"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"

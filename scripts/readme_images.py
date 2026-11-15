"""Build the README images from the rendered screens, so they stay in step with the code.

    uv run python scripts/render_screens.py      # screens/out/*.png (demo data)
    uv run python scripts/readme_images.py       # docs/assets/readme/*.png

Each screen is shown at 2x with crisp pixels, on a paper card with rounded corners and a soft
shadow. Captures of the interactive prototype are made separately with readme-forge's rf.py.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "screens" / "out"
DEST = ROOT / "docs" / "assets" / "readme"
BG = (236, 238, 241)
SCALE = 2
RADIUS = 22
PAD = 18          # paper margin around the screen, like the panel's bezel edge
GAP = 40
MARGIN = 56


def card(name: str) -> Image.Image:
    """One screen at 2x on a rounded white card with a soft shadow (RGBA, shadow included)."""
    src = Image.open(OUT / f"{name}.png").convert("L")
    w, h = src.size[0] * SCALE, src.size[1] * SCALE
    screen = src.resize((w, h), Image.Resampling.NEAREST).convert("RGB")
    cw, ch = w + 2 * PAD, h + 2 * PAD
    face = Image.new("RGB", (cw, ch), (250, 250, 248))
    face.paste(screen, (PAD, PAD))
    # a hairline around the glass, as on the device
    ImageDraw.Draw(face).rectangle([PAD - 1, PAD - 1, PAD + w, PAD + h], outline=(214, 214, 210), width=2)
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], RADIUS, fill=255)
    blur = 26
    out = Image.new("RGBA", (cw + 4 * blur, ch + 4 * blur), (0, 0, 0, 0))
    shadow = Image.new("L", out.size, 0)
    shadow.paste(mask, (2 * blur, 2 * blur + 10))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * 0.32))
    out.putalpha(shadow)
    out = Image.composite(Image.new("RGBA", out.size, (24, 30, 40, 255)), Image.new("RGBA", out.size, (0, 0, 0, 0)), shadow)
    face_rgba = face.convert("RGBA")
    face_rgba.putalpha(mask)
    out.alpha_composite(face_rgba, (2 * blur, 2 * blur))
    return out


def sheet(names: list[str], cols: int, dest: str, width: int | None = None) -> None:
    cards = [card(n) for n in names]
    cw = max(c.width for c in cards)
    ch = max(c.height for c in cards)
    rows = (len(cards) + cols - 1) // cols
    # cards carry their own shadow margin, so overlap that margin instead of adding it to the gap
    inset = 52
    W = MARGIN * 2 + cols * (cw - 2 * inset) + (cols - 1) * GAP
    H = MARGIN * 2 + rows * (ch - 2 * inset) + (rows - 1) * GAP
    img = Image.new("RGBA", (W, H), BG + (255,))
    for i, c in enumerate(cards):
        r, k = divmod(i, cols)
        x = MARGIN + k * (cw - 2 * inset + GAP) - inset + (cw - c.width) // 2
        y = MARGIN + r * (ch - 2 * inset + GAP) - inset + (ch - c.height) // 2
        img.alpha_composite(c, (x, y))
    img = img.convert("RGB")
    if width and img.width > width:
        img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
    DEST.mkdir(parents=True, exist_ok=True)
    # The screens hold four grays and the cards a few shadow tones: a 64-colour palette is lossless to the eye.
    img.quantize(colors=64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(DEST / dest, optimize=True)
    print(f"{dest}: {img.size[0]}x{img.size[1]}, {(DEST / dest).stat().st_size // 1024} KB")


def main() -> None:
    sheet(["board", "approve_h2"], 2, "work.png", 2400)
    sheet(["today", "countdown"], 2, "day.png", 2400)
    sheet(["photo", "note"], 2, "fridge.png", 2400)
    sheet(["listening", "voice_result"], 2, "voice.png", 2400)
    sheet(["reader_1", "art"], 2, "read-sleep.png", 2400)


if __name__ == "__main__":
    main()

"""Render every Sticky screen: Jinja template -> HTML -> headless Chromium -> 4 gray levels.

The output is exactly what the device would show, plus a hotspot list per frame
(rectangles of every element with data-tap / data-hold) that firmware can map touches to.

    uv run python scripts/render_screens.py            # all frames
    uv run python scripts/render_screens.py board      # some frames
"""

from __future__ import annotations

import copy
import math
import json
import subprocess
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from PIL import Image, ImageEnhance, ImageOps

ROOT = Path(__file__).resolve().parent.parent
SCREENS = ROOT / "screens"
OUT = SCREENS / "out"
LEVELS = (0, 85, 170, 255)


def palette_image() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat = []
    for v in LEVELS:
        flat += [v, v, v]
    pal.putpalette(flat + [0] * (768 - len(flat)))
    return pal


def dither_photo(src: Path, dst: Path, size: tuple[int, int], gamma: float = 0.92, contrast: float = 1.08) -> None:
    """Crop to size, lift for paper, then error-diffuse to the 4 panel levels."""
    im = Image.open(src).convert("L")
    im = ImageOps.fit(im, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    im = ImageOps.autocontrast(im, cutoff=1)
    im = im.point(lambda v: int(255 * ((v / 255) ** gamma)))
    im = ImageEnhance.Contrast(im).enhance(contrast)
    im = ImageEnhance.Sharpness(im).enhance(1.25)
    q = im.convert("RGB").quantize(palette=palette_image(), dither=Image.Dither.FLOYDSTEINBERG)
    q.convert("L").save(dst)


def snap(path: Path) -> None:
    """Nearest of the 4 levels: anti-aliased edges become the panel's own grays."""
    im = Image.open(path).convert("L")
    lut = [min(LEVELS, key=lambda lv: abs(lv - v)) for v in range(256)]
    im.point(lut).save(path)


def build(names: list[str]) -> list[dict]:
    flow = json.loads((SCREENS / "flow.json").read_text())
    data = json.loads((SCREENS / "demo" / "data.json").read_text())
    env = Environment(loader=FileSystemLoader(SCREENS / "templates"), autoescape=True)
    env.filters.update(cos=math.cos, sin=math.sin)
    (OUT / "html").mkdir(parents=True, exist_ok=True)
    (OUT / "img").mkdir(parents=True, exist_ok=True)

    for photo in data.get("photos", []):
        w, h = photo["size"]
        dither_photo(SCREENS / "demo" / photo["src"], OUT / "img" / photo["out"], (w, h),
                     photo.get("gamma", 0.9), photo.get("contrast", 1.18))

    jobs = []
    for fid, f in flow["frames"].items():
        if names and fid not in names:
            continue
        d = copy.deepcopy(data)
        for sid, patch in f.get("patch_sessions", {}).items():
            for s in d["sessions"]:
                if s["id"] == sid:
                    s.update(patch)
        d.update(f.get("data", {}))
        portrait = f.get("orient") == "portrait"
        w, h = (480, 800) if portrait else (800, 480)
        deck_as = f.get("deck_as", fid)
        ctx = dict(d=d, frame=fid, w=w, h=h, title=f.get("title", ""),
                   deck_len=len(flow["deck"]),
                   deck_idx=flow["deck"].index(deck_as) if deck_as in flow["deck"] else -1,
                   **f.get("set", {}))
        html = env.get_template(f["template"] + ".html.j2").render(**ctx)
        page = OUT / "html" / f"{fid}.html"
        page.write_text(html)
        jobs.append({"id": fid, "html": str(page), "png": str(OUT / f"{fid}.png"), "w": w, "h": h})
    return jobs


def main() -> None:
    jobs = build(sys.argv[1:])
    spec = OUT / "jobs.json"
    spec.write_text(json.dumps(jobs))
    subprocess.run(["node", str(ROOT / "scripts" / "shoot_screens.mjs"), str(spec)], check=True)
    for j in jobs:
        snap(Path(j["png"]))
    flow = json.loads((SCREENS / "flow.json").read_text())
    hotspots = json.loads((OUT / "hotspots.json").read_text()) if (OUT / "hotspots.json").exists() else {}
    hotspots.update(json.loads((OUT / "hotspots.new.json").read_text()))
    (OUT / "hotspots.json").write_text(json.dumps(hotspots, indent=1))
    (OUT / "hotspots.new.json").unlink()
    manifest = {"deck": flow["deck"], "actions": flow["actions"], "holds": flow.get("holds", {}),
                "scroll": flow.get("scroll", {}), "frames": {}}
    for fid, f in flow["frames"].items():
        portrait = f.get("orient") == "portrait"
        manifest["frames"][fid] = {"img": f"{fid}.png", "w": 480 if portrait else 800, "h": 800 if portrait else 480,
                                   "orient": f.get("orient", "landscape"), "deck_as": f.get("deck_as", fid),
                                   "hotspots": hotspots.get(fid, [])}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"rendered {len(jobs)} frames -> {OUT}")


if __name__ == "__main__":
    main()

"""Overlay graphics borrowed from the explainer/news-documentary skills, in the parchment style:
  * stat:     a big number that counts up to its value (with a small caption under it)
  * headline: a vintage newspaper clipping that slams onto the shot (masthead + headline + column rules)
"""
from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

INK = (52, 36, 22)
PAPER = (241, 228, 196)
NEWS = (233, 224, 200)
SEAL = (156, 61, 34)

NUM_RE = re.compile(r"^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$")


def _font(fonts_dir: Path | None, names: tuple[str, ...], size: int) -> ImageFont.FreeTypeFont:
    for base in ([fonts_dir] if fonts_dir else []) + [Path(__file__).resolve().parent.parent / "assets" / "fonts",
                                                       Path("/usr/share/fonts/truetype/dejavu")]:
        for name in names:
            if (base / name).is_file():
                return ImageFont.truetype(str(base / name), size)
    return ImageFont.truetype("DejaVuSerif-Bold.ttf", size)


# ------------------------------------------------------------------------------ stat

def count_time(text: str, window: float) -> float:
    return min(1.4, max(0.5, window * 0.45))


def stat_display(text: str, progress: float) -> str:
    """The number in `text` at count-up progress 0..1 (ease-out), keeping its format.
    Times like 3:28:53 or text without a number are shown as they are."""
    m = NUM_RE.match(text)
    if progress >= 1 or not m or ":" in text:
        return text
    pre, num, post = m.groups()
    p = 1 - (1 - max(0.0, progress)) ** 3
    decimals = len(num.split(".")[1]) if "." in num else 0
    value = float(num.replace(",", "")) * p
    shown = f"{value:,.{decimals}f}" if "," in num else f"{value:.{decimals}f}"
    return f"{pre}{shown}{post}"


@lru_cache(maxsize=256)
def stat_image(text: str, label: str, fonts_dir: Path | None, frame_h: int) -> Image.Image:
    big = _font(fonts_dir, ("Cinzel-700.woff", "Cinzel-700.ttf"), int(frame_h * 0.15))
    small = _font(fonts_dir, ("Cinzel-700.woff", "Cinzel-700.ttf"), int(frame_h * 0.042))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tb = probe.textbbox((0, 0), text, font=big)
    lb = probe.textbbox((0, 0), label, font=small) if label else (0, 0, 0, 0)
    pad = int(frame_h * 0.035)
    rule = max(4, frame_h // 200)
    w = max(tb[2] - tb[0], lb[2] - lb[0]) + pad * 3
    h = (tb[3] - tb[1]) + (lb[3] - lb[1]) + pad * 3 + rule * 3
    im = Image.new("RGBA", (w + 12, h + 12), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(frame_h * 0.02)
    d.rounded_rectangle((8, 8, w + 8, h + 8), r, fill=(0, 0, 0, 70))
    d.rounded_rectangle((0, 0, w, h), r, fill=PAPER + (245,), outline=INK + (255,), width=max(3, frame_h // 270))
    x = (w - (tb[2] - tb[0])) // 2 - tb[0]
    y = pad - tb[1]
    d.text((x + 4, y + 5), text, font=big, fill=(0, 0, 0, 60))
    d.text((x, y), text, font=big, fill=INK + (255,))
    ry = pad + (tb[3] - tb[1]) + pad // 2 + rule
    d.line((w * 0.3, ry, w * 0.7, ry), fill=SEAL + (255,), width=rule)
    if label:
        d.text(((w - (lb[2] - lb[0])) // 2 - lb[0], ry + rule + pad // 2 - lb[1]), label, font=small, fill=SEAL + (255,))
    return im


# ------------------------------------------------------------------------------ headline

def _wrap(text: str, font, width: int, draw) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        trial = f"{cur} {wd}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    if len(lines) == 2:                                        # balance two lines (no lonely last word)
        best = None
        for i in range(1, len(words)):
            a, b = " ".join(words[:i]), " ".join(words[i:])
            wmax = max(draw.textlength(a, font=font), draw.textlength(b, font=font))
            if wmax <= width and (best is None or wmax < best[0]):
                best = (wmax, [a, b])
        lines = best[1] if best else lines
    elif len(lines) == 3:
        best = None
        for i in range(1, len(words) - 1):
            for j in range(i + 1, len(words)):
                parts = [" ".join(words[:i]), " ".join(words[i:j]), " ".join(words[j:])]
                wmax = max(draw.textlength(p, font=font) for p in parts)
                if wmax <= width and (best is None or wmax < best[0]):
                    best = (wmax, parts)
        lines = best[1] if best else lines
    return lines


@lru_cache(maxsize=32)
def headline_image(text: str, label: str, fonts_dir: Path | None, frame_h: int) -> Image.Image:
    """A torn newspaper clipping, slightly rotated (stable per headline)."""
    seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
    rng = np.random.default_rng(seed)
    cw = int(frame_h * 0.95)                                   # clipping width
    head = _font(fonts_dir, ("DejaVuSerifCondensed-Bold.ttf", "DejaVuSerif-Bold.ttf"), int(frame_h * 0.075))
    mast = _font(fonts_dir, ("Cinzel-700.woff", "Cinzel-700.ttf"), int(frame_h * 0.028))
    pad = int(frame_h * 0.04)
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = _wrap(text.upper(), head, cw - 2 * pad, probe)[:3]
    lh = int(frame_h * 0.085)
    mast_h = int(frame_h * 0.05) if label else 0
    body_rows = 4
    ch = pad + mast_h + (pad // 2 if label else 0) + lh * len(lines) + pad // 2 + body_rows * int(frame_h * 0.026) + pad
    paper = Image.new("RGBA", (cw, ch), NEWS + (255,))
    # yellowed, uneven paper
    g = rng.normal(0, 1, (ch // 6 + 1, cw // 6 + 1)).astype(np.float32)
    g = np.asarray(Image.fromarray(((g * 22) + 128).clip(0, 255).astype(np.uint8)).resize((cw, ch), Image.BICUBIC), np.float32)
    arr = np.asarray(paper, np.float32)
    arr[..., :3] += ((g - 128) * 0.18)[..., None]
    yy, xx = np.mgrid[0:ch, 0:cw]
    edge = np.minimum(np.minimum(xx, cw - 1 - xx), np.minimum(yy, ch - 1 - yy)).astype(np.float32)
    arr[..., :3] -= (np.clip(1 - edge / (frame_h * 0.06), 0, 1) ** 2 * 28)[..., None] * np.array([0.6, 0.8, 1.2])
    paper = Image.fromarray(arr.clip(0, 255).astype(np.uint8), "RGBA")
    d = ImageDraw.Draw(paper)
    y = pad
    if label:
        mb = d.textbbox((0, 0), label.upper(), font=mast)
        d.text(((cw - (mb[2] - mb[0])) // 2 - mb[0], y - mb[1]), label.upper(), font=mast, fill=INK + (255,))
        y += mast_h
        d.line((pad, y - 8, cw - pad, y - 8), fill=INK + (255,), width=3)
        d.line((pad, y - 2, cw - pad, y - 2), fill=INK + (255,), width=1)
        y += pad // 2
    for ln in lines:
        b = d.textbbox((0, 0), ln, font=head)
        d.text(((cw - (b[2] - b[0])) // 2 - b[0], y - b[1]), ln, font=head, fill=(25, 18, 12, 255))
        y += lh
    y += pad // 2
    col_gap = int(frame_h * 0.025)
    col_w = (cw - 2 * pad - col_gap) // 2
    row = int(frame_h * 0.026)
    for r in range(body_rows):                                 # greyed text lines suggest the article body
        for c in range(2):
            x0 = pad + c * (col_w + col_gap)
            ln_w = col_w if r < body_rows - 1 else int(col_w * rng.uniform(0.4, 0.8))
            d.line((x0, y + r * row + row // 2, x0 + ln_w, y + r * row + row // 2), fill=(90, 80, 66, 150), width=max(3, row // 3))
    # torn edges
    mask = Image.new("L", (cw, ch), 0)
    md = ImageDraw.Draw(mask)
    j = frame_h * 0.008
    pts = []
    for i in range(0, 41):
        pts.append((cw * i / 40, rng.uniform(0, j * 2)))
    for i in range(0, 21):
        pts.append((cw - rng.uniform(0, j), ch * i / 20))
    for i in range(40, -1, -1):
        pts.append((cw * i / 40, ch - rng.uniform(0, j * 2)))
    for i in range(20, -1, -1):
        pts.append((rng.uniform(0, j), ch * i / 20))
    md.polygon(pts, fill=255)
    paper.putalpha(mask)
    angle = float(rng.uniform(-3.0, 3.0)) or 1.5
    rot = paper.rotate(angle, resample=Image.BICUBIC, expand=True)
    shadow = Image.new("RGBA", rot.size, (0, 0, 0, 0))
    shadow.putalpha(rot.split()[-1].point(lambda v: int(v * 0.45)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(frame_h * 0.012))
    out = Image.new("RGBA", (rot.width + 30, rot.height + 30), (0, 0, 0, 0))
    out.alpha_composite(shadow, (18, 22))
    out.alpha_composite(rot, (0, 0))
    return out


def headline_scale(dt: float) -> tuple[float, float]:
    """(scale, alpha) of the slam-in: drops from 1.35x onto the page in 0.28 s with a tiny settle."""
    if dt <= 0:
        return 1.35, 0.0
    k = min(1.0, dt / 0.28)
    s = 1.0 + 0.35 * (1 - k) ** 3
    if dt > 0.28:
        s = 1.0 - 0.015 * math.sin(min(1.0, (dt - 0.28) / 0.18) * math.pi)
    return s, min(1.0, dt / 0.12)

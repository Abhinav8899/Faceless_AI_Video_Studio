"""Frame compositor for code-driven shots.

Renders a shot frame by frame with Pillow and pipes raw RGB to ffmpeg:
  * background: a still image with a camera move, or the frames of an existing video
  * characters: cut-outs from the character library, with mouth flap driven by the
    voice audio, timed expression changes, idle breathing and a small squash "pop"
  * overlays: pop-in labels, dates and titles in the parchment style
  * finish: a light paper vignette so every shot type shares one look
"""
from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from pipeline import graphics

MOUTHS = ("closed", "open")


class ComposeError(RuntimeError):
    pass


# --------------------------------------------------------------------------- easing / camera


def ease_in_out(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def ease_out_back(x: float) -> float:
    x = min(1.0, max(0.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


CAMERA_MOVES = ("push_in", "pull_out", "pan_left", "pan_right", "static")


def camera_box(move: str, progress: float, width: int, height: int,
               strength: float = 0.08, focus: tuple[float, float] = (0.5, 0.5)) -> tuple[float, float, float, float]:
    """Crop box (x0, y0, x1, y1) in source pixels for a camera move at progress 0..1."""
    p = ease_in_out(progress)
    if move == "push_in":
        zoom = 1 + strength * p
    elif move == "pull_out":
        zoom = 1 + strength * (1 - p)
    elif move in ("pan_left", "pan_right"):
        zoom = 1 + strength
    elif move == "static":
        zoom = 1.0
    else:
        raise ComposeError(f"unknown camera move {move!r} (use one of {CAMERA_MOVES})")
    cw, ch = width / zoom, height / zoom
    if move in ("pan_left", "pan_right"):
        span = width - cw
        x0 = span * (1 - p) if move == "pan_left" else span * p
        y0 = (height - ch) * focus[1]
    else:
        x0 = focus[0] * width - cw / 2
        y0 = focus[1] * height - ch / 2
    x0 = min(max(x0, 0.0), width - cw)
    y0 = min(max(y0, 0.0), height - ch)
    return (x0, y0, x0 + cw, y0 + ch)


# --------------------------------------------------------------------------- audio


def audio_envelope(path: str | Path, fps: int) -> np.ndarray:
    """Per-frame loudness 0..1 of an audio file (RMS, lightly smoothed, normalised)."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
        capture_output=True, check=True,
    ).stdout
    samples = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    hop = max(1, 16000 // fps)
    frames = max(1, -(-len(samples) // hop))          # ceil, so the last partial frame is kept but never empty
    rms = np.array([np.sqrt(np.mean(samples[i * hop:(i + 1) * hop] ** 2) + 1e-12) if len(samples) else 0.0
                    for i in range(frames)])
    rms = np.convolve(rms, np.ones(2) / 2, mode="same")
    peak = float(rms.max()) or 1.0
    return rms / peak


def mouth_track(envelope: np.ndarray, frames: int, threshold: float = 0.16, cadence: int = 3) -> list[str]:
    """closed/open per frame: while the voice is audible the mouth alternates every `cadence` frames."""
    track: list[str] = []
    for i in range(frames):
        voiced = i < len(envelope) and envelope[i] > threshold
        track.append("open" if voiced and (i // cadence) % 2 == 0 else "closed")
    return track


# --------------------------------------------------------------------------- character library


@dataclass(frozen=True)
class Sprite:
    path: Path
    feet: tuple[int, int]  # feet anchor in cut-out pixels


class Library:
    """Reads <lib>/index.json written by the character library post-processing step."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        index = self.root / "index.json"
        if not index.is_file():
            raise ComposeError(f"character library index not found: {index}")
        data = json.loads(index.read_text())
        self.entries: dict[tuple[str, str, str, str], Sprite] = {}
        for name, items in data.get("characters", {}).items():
            for e in items:
                if e.get("kind") != "pose":
                    continue
                key = (name, e["pose"], e["expression"], e["mouth"])
                self.entries[key] = Sprite(self.root / name / e["cutout"], tuple(e["feet_anchor"]))

    def characters(self) -> list[str]:
        return sorted({k[0] for k in self.entries})

    def poses(self, name: str) -> list[str]:
        return sorted({k[1] for k in self.entries if k[0] == name})

    def expressions(self, name: str, pose: str) -> list[str]:
        return sorted({k[2] for k in self.entries if k[0] == name and k[1] == pose})

    def has_pose(self, name: str, pose: str) -> bool:
        return any(k[0] == name and k[1] == pose for k in self.entries)

    def sprite(self, name: str, pose: str, expression: str, mouth: str) -> Sprite:
        """Exact match, else fall back: same expression closed mouth, then neutral, then any expression."""
        for key in ((name, pose, expression, mouth), (name, pose, expression, "closed"),
                    (name, pose, "neutral", mouth), (name, pose, "neutral", "closed")):
            if key in self.entries:
                return self.entries[key]
        for key, sprite in sorted(self.entries.items()):
            if key[0] == name and key[1] == pose and key[3] == "closed":
                return sprite
        raise ComposeError(f"no image for {name}/{pose} in {self.root}")


    def exact(self, name: str, pose: str, expression: str, mouth: str) -> Sprite | None:
        return self.entries.get((name, pose, expression, mouth))


# --------------------------------------------------------------------------- rig (jitter-free character)
#
# Every library image is a separate AI generation, so swapping whole images (mouth open/closed,
# expressions) makes the body shift a few pixels on every swap: visible jitter. A rig fixes that:
#   1. all variants are aligned to the pose's base image (phase correlation on the cut-out),
#   2. only the pixels that actually changed in the head area are patched onto the base:
#      the mouth region for talking, the face for expressions,
# so the body always comes from one single image.


def _phase_shift(ref: np.ndarray, img: np.ndarray) -> tuple[int, int]:
    """(dy, dx) that moves `img` onto `ref` (both 2-D float arrays, top-left aligned)."""
    h, w = max(ref.shape[0], img.shape[0]), max(ref.shape[1], img.shape[1])
    a = np.zeros((h, w), np.float32); a[:ref.shape[0], :ref.shape[1]] = ref
    b = np.zeros((h, w), np.float32); b[:img.shape[0], :img.shape[1]] = img
    cross = np.fft.rfft2(a) * np.conj(np.fft.rfft2(b))
    cross /= np.abs(cross) + 1e-6
    corr = np.fft.irfft2(cross, s=(h, w))
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    return int(dy), int(dx)


def _signature(im: Image.Image) -> np.ndarray:
    """Alpha-weighted ink edges: robust for aligning two drawings of the same pose."""
    a = np.asarray(im, np.float32)
    gray = a[..., :3].mean(-1) * (a[..., 3] / 255.0)
    gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    return gx + gy + a[..., 3] * 0.2


def _align_to(ref: Image.Image, img: Image.Image) -> Image.Image:
    dy, dx = _phase_shift(_signature(ref), _signature(img))
    if max(abs(dy), abs(dx)) > max(ref.size) // 8:      # implausible: images too different, keep as-is
        dy = dx = 0
    out = Image.new("RGBA", ref.size, (0, 0, 0, 0))
    out.paste(img, (dx, dy))
    return out


def _mouth_peak(base: Image.Image, variant: Image.Image, zone: tuple[int, int, int, int],
                window: tuple[int, int, int, int] | None = None) -> tuple[int, int] | None:
    """(y, x) of the biggest blob of newly dark pixels (an open mouth's interior) inside zone,
    optionally only inside window (x0, y0, x1, y1)."""
    a = np.asarray(base, np.float32)
    b = np.asarray(variant, np.float32)
    x0, y0, x1, y1 = zone
    if window is not None:
        x0, y0 = max(x0, window[0]), max(y0, window[1])
        x1, y1 = min(x1, window[2]), min(y1, window[3])
        if x1 <= x0 or y1 <= y0:
            return None
    darker = np.zeros(a.shape[:2], np.uint8)
    darker[y0:y1, x0:x1] = ((b[y0:y1, x0:x1, :3].mean(-1) < a[y0:y1, x0:x1, :3].mean(-1) - 45) * 255).astype(np.uint8)
    dens = np.asarray(Image.fromarray(darker).filter(ImageFilter.GaussianBlur(12)), np.float32)
    if dens.max() <= 0:
        return None
    py, px = np.unravel_index(int(np.argmax(dens)), dens.shape)
    return int(py), int(px)


def _patch(base: Image.Image, variant: Image.Image, zone: tuple[int, int, int, int],
           focus: float, grow: int, feather: float, peak_box: tuple[int, int] | None = None,
           anchor: tuple[int, int] | None = None) -> Image.Image:
    """Copy onto `base` only the pixels of `variant` that differ, inside `zone`.

    focus: keep only the densest change (relative to its peak); 0.35 isolates the mouth, ~0.08 a face.
    peak_box: (half_w, half_h) further limits the patch to a box around the strongest change
              (the mouth), so eyes/brows redrawn by the generator do not twitch while talking.
    """
    a = np.asarray(base, np.float32)
    b = np.asarray(variant, np.float32)
    diff = np.abs(a[..., :3] - b[..., :3]).sum(-1) / 3 + np.abs(a[..., 3] - b[..., 3])
    mask = np.zeros(diff.shape, np.float32)
    x0, y0, x1, y1 = zone
    mask[y0:y1, x0:x1] = (diff[y0:y1, x0:x1] > 28).astype(np.float32)
    if mask.max() == 0:
        return base.copy()
    density = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(9)), np.float32)
    region = (density > focus * density.max()).astype(np.uint8) * 255
    if peak_box is not None:
        # an open mouth is the biggest blob of newly *dark* pixels (the mouth interior); redrawn
        # brows/eyes are thin lines, so this finds the mouth even when the eyes changed a lot
        luma_a = a[..., :3].mean(-1)
        luma_b = b[..., :3].mean(-1)
        darker = np.zeros(diff.shape, np.uint8)
        darker[y0:y1, x0:x1] = ((luma_b[y0:y1, x0:x1] < luma_a[y0:y1, x0:x1] - 45) * 255).astype(np.uint8)
        dark_density = np.asarray(Image.fromarray(darker).filter(ImageFilter.GaussianBlur(12)), np.float32)
        peak_map = dark_density if dark_density.max() > 0 else density
        hw, hh = peak_box
        if anchor is not None:
            # the pose's known mouth position: only look for the peak close to it, never at eyes/hair
            ay, ax = anchor
            near = np.zeros_like(peak_map)
            near[max(0, ay - hh):ay + hh, max(0, ax - hw):ax + hw] = 1
            peak_map = peak_map * near
            if peak_map.max() <= 0:
                peak_map = near
        py, px = np.unravel_index(int(np.argmax(peak_map)), peak_map.shape)
        limit = np.zeros_like(region)
        limit[max(0, py - hh):py + hh, max(0, px - hw):px + hw] = 1
        region = region * limit
    region = Image.fromarray(region).filter(ImageFilter.MaxFilter(grow | 1)).filter(ImageFilter.GaussianBlur(feather))
    m = np.asarray(region, np.float32)[..., None] / 255.0
    out = a * (1 - m) + b * m
    return Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGBA")


@dataclass
class Rig:
    frames: dict[tuple[str, str], Image.Image]   # (expression, mouth) -> RGBA, all the base size
    feet: tuple[float, float]                    # in rig pixels
    body_width: int

    def frame(self, expression: str, mouth: str) -> Image.Image:
        for key in ((expression, mouth), (expression, "closed"), ("neutral", mouth), ("neutral", "closed")):
            if key in self.frames:
                return self.frames[key]
        return next(iter(self.frames.values()))


@lru_cache(maxsize=32)
def build_rig(library: "Library", name: str, pose: str, height: int, flip: bool) -> Rig:
    exprs = library.expressions(name, pose)
    base_sp = library.exact(name, pose, "neutral", "closed") or library.sprite(name, pose, exprs[0], "closed")
    base_full = Image.open(base_sp.path).convert("RGBA")
    bbox = base_full.getbbox() or (0, 0, base_full.width, base_full.height)
    fig_h = bbox[3] - bbox[1]
    # the head lives in the upper part of the figure; patches never touch the body below it
    head_zone = (0, 0, base_full.width, bbox[1] + int(fig_h * 0.5))
    frames: dict[tuple[str, str], Image.Image] = {}
    pending: list[tuple[str, Image.Image, Image.Image]] = []
    for expr in exprs:
        closed_sp = library.exact(name, pose, expr, "closed")
        if closed_sp is None:
            continue
        if closed_sp.path == base_sp.path:
            closed = base_full
        else:
            closed = _patch(base_full, _align_to(base_full, Image.open(closed_sp.path).convert("RGBA")),
                            head_zone, focus=0.06, grow=15, feather=5)
        frames[(expr, "closed")] = closed
        open_sp = library.exact(name, pose, expr, "open")
        if open_sp is not None:
            pending.append((expr, closed, _align_to(closed, Image.open(open_sp.path).convert("RGBA"))))
    # Where the mouth is: the median of every expression's open-mouth peak (neutral weighted in).
    # A variant whose "closed" mouth is already open (scared, shocked) has its biggest change at the
    # eyes or hair instead; anchoring keeps the talking patch on the mouth, so the eyes never flicker.
    peak_box = (int(fig_h * 0.075), int(fig_h * 0.045))
    peaks = [pk for _, c, o in pending if (pk := _mouth_peak(c, o, head_zone)) is not None]
    anchor = None
    if peaks:
        ys, xs = sorted(p[0] for p in peaks), sorted(p[1] for p in peaks)
        anchor = (ys[len(ys) // 2], xs[len(xs) // 2])
    for expr, closed, opened in pending:
        frames[(expr, "open")] = _patch(closed, opened, head_zone, focus=0.35, grow=11, feather=4,
                                        peak_box=peak_box, anchor=anchor)
    scale = height / base_full.height
    size = (max(1, round(base_full.width * scale)), height)
    for key, im in frames.items():
        im = im.resize(size, Image.LANCZOS)
        frames[key] = im.transpose(Image.FLIP_LEFT_RIGHT) if flip else im
    fx, fy = base_sp.feet
    if flip:
        fx = base_full.width - fx
    body_w = int(min(bbox[2] - bbox[0], fig_h * 0.55) * scale)
    return Rig(frames, (fx * scale, fy * scale), body_w)


def _place(sprite: Image.Image, feet: tuple[float, float], x: float, y: float,
           sx: float, sy: float) -> tuple[Image.Image, tuple[int, int]]:
    """Scale `sprite` by (sx, sy) about its feet and put the feet at frame point (x, y), with
    sub-pixel accuracy (bicubic affine), so slow motion never snaps between whole pixels."""
    w, h = sprite.size
    fx, fy = feet
    ox = math.floor(x - fx * sx) - 2
    oy = math.floor(y - fy * sy) - 2
    out_w, out_h = math.ceil(w * sx) + 5, math.ceil(h * sy) + 5
    data = (1 / sx, 0, (ox - x) / sx + fx, 0, 1 / sy, (oy - y) / sy + fy)
    return sprite.transform((out_w, out_h), Image.AFFINE, data, resample=Image.BICUBIC), (ox, oy)


# --------------------------------------------------------------------------- shot description


@dataclass
class CharacterPlan:
    name: str
    pose: str
    side: str = "left"                       # left | center | right
    expression: str = "neutral"
    beats: list[tuple[float, str]] = field(default_factory=list)   # (seconds, expression)
    speaking: bool = False
    height_frac: float = 0.80
    flip: bool = False

    def expression_at(self, t: float) -> str:
        current = self.expression
        for start, expr in sorted(self.beats):
            if t >= start:
                current = expr
        return current


@dataclass
class OverlayPlan:
    kind: str            # label | title | date | subscribe | stat | headline
    text: str
    start: float
    end: float
    position: str        # top_left | top_right | top | bottom | center
    label: str = ""      # stat: caption under the number; headline: masthead line


@dataclass
class ShotPlan:
    duration: float
    width: int = 1920
    height: int = 1080
    fps: int = 30
    background: Path | None = None           # still image
    background_video: Path | None = None     # or existing video frames
    camera: str = "push_in"
    camera_strength: float = 0.08
    characters: list[CharacterPlan] = field(default_factory=list)
    audio: Path | None = None                # drives the speaking character's mouth
    overlays: list[OverlayPlan] = field(default_factory=list)
    finish_strength: float = 0.35
    ground: float = 0.965                    # feet line as a fraction of frame height
    fonts_dir: Path | None = None
    map_spec: dict | None = None             # "map" scenes: drawn by pipeline.mapshot instead of a background


# --------------------------------------------------------------------------- overlays


def _font(fonts_dir: Path | None, names: Sequence[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        for base in ([fonts_dir] if fonts_dir else []) + [Path("/usr/share/fonts/truetype/dejavu")]:
            path = base / name
            if path.is_file():
                return ImageFont.truetype(str(path), size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


INK = (52, 36, 22)
PAPER = (241, 228, 196)
SEAL = (156, 61, 34)


def _subscribe_badge(fonts_dir: Path | None, frame_h: int) -> Image.Image:
    """LIKE + SUBSCRIBE call-to-action badge (two pills: parchment LIKE with a heart, red SUBSCRIBE)."""
    size = int(frame_h * 0.068)
    font = _font(fonts_dir, ["Cinzel-700.woff", "Cinzel-700.ttf"], size)
    pad_x, pad_y, gap = int(size * 0.7), int(size * 0.42), int(size * 0.5)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    like_b = probe.textbbox((0, 0), "LIKE", font=font)
    sub_b = probe.textbbox((0, 0), "SUBSCRIBE", font=font)
    th = max(like_b[3] - like_b[1], sub_b[3] - sub_b[1])
    h = th + 2 * pad_y
    heart = int(h * 0.5)
    like_w = (like_b[2] - like_b[0]) + 2 * pad_x + heart + int(size * 0.3)
    sub_w = (sub_b[2] - sub_b[0]) + 2 * pad_x
    w = like_w + gap + sub_w
    im = Image.new("RGBA", (w + 10, h + 10), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = h // 2
    border = max(3, size // 14)
    for x0, x1 in ((0, like_w), (like_w + gap, w)):
        d.rounded_rectangle((x0 + 6, 6, x1 + 6, h + 6), r, fill=(0, 0, 0, 80))
    d.rounded_rectangle((0, 0, like_w, h), r, fill=PAPER + (255,), outline=INK + (255,), width=border)
    d.rounded_rectangle((like_w + gap, 0, w, h), r, fill=(196, 38, 30, 255), outline=INK + (255,), width=border)
    # heart: two circles + a triangle
    hx, hy, hs = pad_x, (h - heart) // 2, heart
    d.ellipse((hx, hy, hx + hs * 0.56, hy + hs * 0.56), fill=SEAL + (255,))
    d.ellipse((hx + hs * 0.44, hy, hx + hs, hy + hs * 0.56), fill=SEAL + (255,))
    d.polygon([(hx + hs * 0.03, hy + hs * 0.38), (hx + hs * 0.97, hy + hs * 0.38), (hx + hs * 0.5, hy + hs)], fill=SEAL + (255,))
    d.text((pad_x + heart + int(size * 0.3) - like_b[0], pad_y - like_b[1]), "LIKE", font=font, fill=INK + (255,))
    d.text((like_w + gap + pad_x - sub_b[0], pad_y - sub_b[1]), "SUBSCRIBE", font=font, fill=(255, 250, 240, 255))
    return im


def _overlay_image(ov: OverlayPlan, fonts_dir: Path | None, frame_h: int) -> Image.Image:
    if ov.kind == "stat":
        return graphics.stat_image(ov.text, ov.label, fonts_dir, frame_h)
    if ov.kind == "headline":
        return graphics.headline_image(ov.text, ov.label, fonts_dir, frame_h)
    if ov.kind == "subscribe":
        return _subscribe_badge(fonts_dir, frame_h)
    if ov.kind == "title":
        font = _font(fonts_dir, ["Cinzel-700.woff", "Cinzel-700.ttf"], int(frame_h * 0.085))
        pad = int(frame_h * 0.02)
        probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
        b = probe.textbbox((0, 0), ov.text, font=font)
        w, h = b[2] - b[0] + pad * 4, b[3] - b[1] + pad * 3
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.text((pad * 2 - b[0] + 4, pad - b[1] + 5), ov.text, font=font, fill=(0, 0, 0, 90))
        d.text((pad * 2 - b[0], pad - b[1]), ov.text, font=font, fill=INK + (255,))
        y = h - pad
        d.line((pad * 2, y, w - pad * 2, y), fill=SEAL + (255,), width=max(3, frame_h // 270))
        return im
    # label / date: a small parchment card with an ink border
    size = int(frame_h * 0.05)
    font = _font(fonts_dir, ["Cinzel-700.woff", "Cinzel-700.ttf"], size)
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    b = probe.textbbox((0, 0), ov.text, font=font)
    padx, pady = int(size * 0.7), int(size * 0.45)
    w, h = b[2] - b[0] + 2 * padx, b[3] - b[1] + 2 * pady
    im = Image.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    r = int(size * 0.25)
    d.rounded_rectangle((6, 6, w + 6, h + 6), r, fill=(0, 0, 0, 70))
    d.rounded_rectangle((0, 0, w, h), r, fill=PAPER + (255,), outline=INK + (255,), width=max(3, size // 14))
    if ov.kind == "date":
        d.rectangle((0, 0, max(6, size // 5), h), fill=SEAL + (255,))
    d.text((padx - b[0], pady - b[1]), ov.text, font=font, fill=INK + (255,))
    return im


def _overlay_pos(ov: OverlayPlan, im: Image.Image, w: int, h: int) -> tuple[int, int]:
    mx, my = int(w * 0.05), int(h * 0.07)
    pos = ov.position
    if pos == "top_left":
        return mx, my
    if pos == "top_right":
        return w - mx - im.width, my
    if pos == "bottom":
        return (w - im.width) // 2, h - my - im.height
    if pos == "center":
        return (w - im.width) // 2, (h - im.height) // 2
    return (w - im.width) // 2, my  # top


def _draw_overlays(frame: Image.Image, overlays: list[tuple[OverlayPlan, Image.Image]], t: float,
                   fonts_dir: Path | None = None) -> None:
    w, h = frame.size
    for ov, im in overlays:
        if not (ov.start <= t <= ov.end):
            continue
        k_in = (t - ov.start) / 0.22
        k_out = (ov.end - t) / 0.18
        scale = ease_out_back(min(1.0, k_in)) if k_in < 1 else 1.0
        alpha = min(1.0, k_in * 2, max(0.0, k_out))
        src = im
        if ov.kind == "headline":                 # slams down onto the page instead of popping up
            scale, a_in = graphics.headline_scale(t - ov.start)
            alpha = min(a_in, max(0.0, k_out))
        elif ov.kind == "stat":                   # the number counts up to its value
            shown = graphics.stat_display(ov.text, (t - ov.start) / graphics.count_time(ov.text, ov.end - ov.start))
            if shown != ov.text:
                src = graphics.stat_image(shown, ov.label, fonts_dir, h)
        if scale <= 0.05 or alpha <= 0.02:
            continue
        sized = src if scale == 1.0 else src.resize((max(1, int(src.width * scale)), max(1, int(src.height * scale))), Image.BICUBIC)
        if alpha < 1:
            a = sized.split()[-1].point(lambda v: int(v * alpha))
            sized = sized.copy(); sized.putalpha(a)
        x, y = _overlay_pos(ov, im, w, h)
        frame.alpha_composite(sized, (x + (im.width - sized.width) // 2, y + (im.height - sized.height) // 2))


# --------------------------------------------------------------------------- finish


@lru_cache(maxsize=8)
def _finish_layer(w: int, h: int, strength: float) -> Image.Image | None:
    if strength <= 0:
        return None
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = (xx - w / 2) / (w / 2), (yy - h / 2) / (h / 2)
    vignette = np.clip((np.sqrt(dx ** 2 + dy ** 2) - 0.55) / 0.75, 0, 1) ** 1.6
    rng = np.random.default_rng(7)
    grain = rng.normal(0, 1, (h // 4 + 1, w // 4 + 1)).astype(np.float32)
    grain = np.asarray(Image.fromarray(((grain * 18) + 128).clip(0, 255).astype(np.uint8)).resize((w, h), Image.BICUBIC), np.float32)
    alpha = (vignette * 150 + np.abs(grain - 128) * 0.35) * strength
    layer = np.zeros((h, w, 4), np.uint8)
    layer[..., 0], layer[..., 1], layer[..., 2] = 70, 45, 20   # sepia ink
    layer[..., 3] = alpha.clip(0, 255).astype(np.uint8)
    return Image.fromarray(layer, "RGBA")


# --------------------------------------------------------------------------- frame sources


def _video_frames(path: Path, w: int, h: int, fps: int) -> Iterator[Image.Image]:
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    size = w * h * 3
    last = None
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            last = Image.frombytes("RGB", (w, h), buf)
            yield last
    finally:
        proc.stdout.close()
        proc.wait()
    while last is not None:          # hold the last frame if the video is shorter than the shot
        yield last


# --------------------------------------------------------------------------- render


def _slot_x(side: str, w: int) -> float:
    return {"left": 0.28, "center": 0.5, "right": 0.72}.get(side, 0.5) * w


def render(plan: ShotPlan, library: Library | None, destination: str | Path, crf: int = 18,
           preset: str = "medium") -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    W, H, fps = plan.width, plan.height, plan.fps
    frames = max(1, int(round(plan.duration * fps)))

    mapper = None
    if plan.map_spec is not None:
        from pipeline.mapshot import MapShot
        mapper = MapShot(plan.map_spec, W, H, plan.duration, plan.fonts_dir)
    if plan.background is None and plan.background_video is None and mapper is None:
        raise ComposeError("shot needs a background image or video")
    bg_still = None
    if plan.background is not None:
        src = Image.open(plan.background).convert("RGB")
        # cover the frame at the source's own resolution, then crop per frame for the camera move
        scale = max(W / src.width, H / src.height)
        bg_still = src.resize((math.ceil(src.width * scale), math.ceil(src.height * scale)), Image.LANCZOS)
        ox, oy = (bg_still.width - W) // 2, (bg_still.height - H) // 2
        bg_still = bg_still.crop((ox, oy, ox + W, oy + H))
    video_iter = _video_frames(plan.background_video, W, H, fps) if plan.background_video else None

    mouth = ["closed"] * frames
    if plan.audio is not None and any(c.speaking for c in plan.characters):
        mouth = mouth_track(audio_envelope(plan.audio, fps), frames)

    overlays = [(ov, _overlay_image(ov, plan.fonts_dir, H)) for ov in plan.overlays]
    finish = _finish_layer(W, H, plan.finish_strength)

    shadow_cache: dict[int, Image.Image] = {}

    def shadow(width: int) -> Image.Image:
        if width not in shadow_cache:
            s = Image.new("RGBA", (width + 80, 110), (0, 0, 0, 0))
            ImageDraw.Draw(s).ellipse((40, 30, width + 40, 80), fill=(60, 40, 20, 85))
            shadow_cache[width] = s.filter(ImageFilter.GaussianBlur(12))
        return shadow_cache[width]

    focus = (0.5, 0.45)
    if plan.characters:
        speaker = next((c for c in plan.characters if c.speaking), plan.characters[0])
        focus = (_slot_x(speaker.side, W) / W, 0.5)

    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-an", str(destination)],
        stdin=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        for i in range(frames):
            t = i / fps
            frame = mapper.frame(t) if mapper else (next(video_iter) if video_iter else bg_still).convert("RGBA")
            for c in plan.characters:
                rig = build_rig(library, c.name, c.pose, int(H * c.height_frac), c.flip)
                sprite = rig.frame(c.expression_at(t), mouth[i] if c.speaking else "closed")
                # slow breathing (sub-pixel, so it never steps) + a small squash pop after expression changes
                phase = sum(map(ord, c.name)) % 7 * 0.3          # stable per character, offsets two characters
                breathe = 1 + 0.004 * math.sin(2 * math.pi * (t + phase) / 3.2)
                pop = 1.0
                for start, _ in c.beats:
                    dt = t - start
                    if 0 <= dt < 0.32:
                        k = dt / 0.32
                        pop *= 1 + 0.05 * math.sin(k * math.pi * 2) * (1 - k)
                sy = breathe * pop
                sx = 1 / math.sqrt(sy)
                # entrance: rise 4% over the first 0.25 s
                rise = (1 - ease_in_out(min(1.0, t / 0.25))) * H * 0.04
                cx = _slot_x(c.side, W)
                feet_y = plan.ground * H
                frame.alpha_composite(shadow(rig.body_width), (int(cx - rig.body_width / 2 - 40), int(feet_y - 55)))
                placed, pos = _place(sprite, rig.feet, cx, feet_y + rise, sx, sy)
                frame.alpha_composite(placed, pos)
            if bg_still is not None and plan.camera != "static":
                box = camera_box(plan.camera, t / max(plan.duration, 1e-6), W, H, plan.camera_strength, focus)
                frame = frame.resize((W, H), Image.BICUBIC, box=box)
            _draw_overlays(frame, overlays, t, plan.fonts_dir)
            if finish is not None:
                frame.alpha_composite(finish)
            proc.stdin.write(frame.convert("RGB").tobytes())
        proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise ComposeError(f"ffmpeg encode failed for {destination}: {err[-1500:]}")
    finally:
        if proc.poll() is None:
            proc.kill()
    return destination

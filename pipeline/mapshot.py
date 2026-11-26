"""Code-drawn parchment maps for "map" scenes (map-animation skill).

One designed world, one camera: the shot opens on a wider view and eases in to the story's area,
then a route draws itself on with a moving ink head, pins pop in with labels, and region names
sit in the paper like a printed atlas. Coastlines, rivers and lakes come from Natural Earth
(public domain, assets/geo). Modern borders are never drawn, so the map suits any era.

The heavy part (land, water, region names) is rasterised once into a large base image; every
frame only crops that base for the camera and draws the route and pins crisply on top.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GEO_DIR = Path(__file__).resolve().parent.parent / "assets" / "geo"

INK = (52, 36, 22)
PAPER = (241, 228, 196)
LAND = (236, 220, 182)
SEA = (203, 196, 170)
RIVER = (120, 128, 128)
SEAL = (156, 61, 34)


def _ease(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return 0.5 - 0.5 * math.cos(math.pi * x)


def _ease_out_back(x: float) -> float:
    x = min(1.0, max(0.0, x))
    c1, c3 = 1.70158, 2.70158
    return 1 + c3 * (x - 1) ** 3 + c1 * (x - 1) ** 2


def merc(lon: float, lat: float) -> tuple[float, float]:
    """Web-Mercator in degree-like units (x = lon, y grows northwards)."""
    lat = max(-85.0, min(85.0, lat))
    return lon, math.degrees(math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)))


def _font(fonts_dir: Path | None, size: int) -> ImageFont.FreeTypeFont:
    for base in ([fonts_dir] if fonts_dir else []) + [Path(__file__).resolve().parent.parent / "assets" / "fonts"]:
        for name in ("Cinzel-700.woff", "Cinzel-700.ttf"):
            if (base / name).is_file():
                return ImageFont.truetype(str(base / name), size)
    return ImageFont.truetype("DejaVuSerif-Bold.ttf", size)


@lru_cache(maxsize=8)
def _features(name: str) -> list[list[list[tuple[float, float]]]]:
    """Polygons (list of rings) or lines (one ring) of a Natural Earth file, projected."""
    path = GEO_DIR / f"{name}.geojson"
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    out: list[list[list[tuple[float, float]]]] = []
    for feat in data.get("features", []):
        g = feat.get("geometry") or {}
        t, c = g.get("type"), g.get("coordinates")
        if t == "Polygon":
            parts = [c]
        elif t == "MultiPolygon":
            parts = c
        elif t == "LineString":
            parts = [[c]]
        elif t == "MultiLineString":
            parts = [[line] for line in c]
        else:
            continue
        for rings in parts:
            out.append([[merc(p[0], p[1]) for p in ring] for ring in rings])
    return out


def _fit(box: tuple[float, float, float, float], aspect: float) -> tuple[float, float, float, float]:
    """Grow a projected box (x0, y0, x1, y1) to the frame aspect around its centre."""
    x0, y0, x1, y1 = box
    cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def _proj_box(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    lon0, lat0, lon1, lat1 = bbox
    x0, y0 = merc(min(lon0, lon1), min(lat0, lat1))
    x1, y1 = merc(max(lon0, lon1), max(lat0, lat1))
    return x0, y0, x1, y1


class MapShot:
    """spec keys (all lon/lat in degrees):
        bbox [lon_min, lat_min, lon_max, lat_max]   the view the camera ends on
        start_bbox (optional)                        the view it starts on (default: 1.7x wider)
        places [{name, lon, lat, at?}]               pins with labels; at = seconds (default staggered)
        route [[lon, lat], ...]                      a path that draws itself on
        route_start / route_end                      seconds (default 0.25*d .. 0.8*d)
        regions [{name, lon, lat}]                   atlas-style names, no pin (seas, countries)
    """

    def __init__(self, spec: dict, width: int, height: int, duration: float, fonts_dir: Path | None = None) -> None:
        self.W, self.H, self.d = width, height, max(duration, 0.5)
        self.spec = spec
        aspect = width / height
        self.end = _fit(_proj_box(spec["bbox"]), aspect)
        if spec.get("start_bbox"):
            self.start = _fit(_proj_box(spec["start_bbox"]), aspect)
        else:
            cx, cy = (self.end[0] + self.end[2]) / 2, (self.end[1] + self.end[3]) / 2
            w, h = (self.end[2] - self.end[0]) * 1.7, (self.end[3] - self.end[1]) * 1.7
            self.start = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        self.cam_dur = min(self.d * 0.6, 4.5)
        self.fonts_dir = fonts_dir
        # base raster covers both views (+margin) with enough pixels for the tighter one
        pad = 0.04
        ux0, uy0 = min(self.start[0], self.end[0]), min(self.start[1], self.end[1])
        ux1, uy1 = max(self.start[2], self.end[2]), max(self.start[3], self.end[3])
        mw, mh = (ux1 - ux0) * pad, (uy1 - uy0) * pad
        self.world = (ux0 - mw, uy0 - mh, ux1 + mw, uy1 + mh)
        tight_w = min(self.start[2] - self.start[0], self.end[2] - self.end[0])
        ppu = 1.4 * width / tight_w
        bw = (self.world[2] - self.world[0]) * ppu
        if bw > 9000:                                   # very deep zooms: cap memory, accept softer start
            ppu *= 9000 / bw
        self.ppu = ppu
        self.base_size = (max(1, int((self.world[2] - self.world[0]) * ppu)),
                          max(1, int((self.world[3] - self.world[1]) * ppu)))
        self.base = self._draw_base()
        self.place_times = self._place_times()
        self.label_font = _font(fonts_dir, int(height * 0.036))

    # ------------------------------------------------------------------ geometry
    def _place_times(self) -> list[float]:
        """A pin on the route pops in when the drawing head reaches it; other pins are staggered
        before the route starts. An explicit `at` always wins."""
        places = self.spec.get("places", [])
        route = [merc(lon, lat) for lon, lat in self.spec.get("route", [])]
        rs, re_ = self.route_window()
        cum = [0.0]
        for a, b in zip(route, route[1:]):
            cum.append(cum[-1] + math.dist(a, b))
        total = cum[-1] or 1.0
        near = (self.end[2] - self.end[0]) * 0.03
        times, free = [], 0
        for p in places:
            if p.get("at") is not None:
                times.append(max(0.0, float(p["at"])))
                continue
            xy = merc(p["lon"], p["lat"])
            best = min(range(len(route)), key=lambda i: math.dist(route[i], xy)) if len(route) >= 2 else None
            if best is not None and math.dist(route[best], xy) <= near:
                f = cum[best] / total
                u = math.acos(max(-1.0, min(1.0, 1 - 2 * f))) / math.pi   # inverse of the route's easing
                times.append(max(0.0, rs + (re_ - rs) * u - 0.1))
            else:
                times.append(min(self.d - 0.8, 0.4 + free * 0.5))
                free += 1
        return times

    def route_window(self) -> tuple[float, float]:
        s = self.spec.get("route_start")
        e = self.spec.get("route_end")
        s = self.d * 0.25 if s is None else s
        e = self.d * 0.8 if e is None else e
        return s, max(s + 0.3, min(e, self.d))

    def _to_base(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.world[0]) * self.ppu, (self.world[3] - y) * self.ppu

    def view_at(self, t: float) -> tuple[float, float, float, float]:
        p = _ease(t / self.cam_dur)
        s, e = self.start, self.end
        scx, scy, sw = (s[0] + s[2]) / 2, (s[1] + s[3]) / 2, s[2] - s[0]
        ecx, ecy, ew = (e[0] + e[2]) / 2, (e[1] + e[3]) / 2, e[2] - e[0]
        w = sw * (ew / sw) ** p                          # geometric zoom: constant perceived speed
        k = (sw - w) / (sw - ew) if abs(sw - ew) > 1e-9 else p
        cx, cy = scx + (ecx - scx) * k, scy + (ecy - scy) * k
        h = w * self.H / self.W
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    # ------------------------------------------------------------------ base raster
    def _draw_base(self) -> Image.Image:
        bw, bh = self.base_size
        span = self.end[2] - self.end[0]
        detail = "10m" if span < 25 else "50m"
        wx0, wy0, wx1, wy1 = self.world

        def visible(rings):
            xs = [p[0] for p in rings[0]]
            ys = [p[1] for p in rings[0]]
            return not (max(xs) < wx0 or min(xs) > wx1 or max(ys) < wy0 or min(ys) > wy1)

        land = Image.new("L", (bw, bh), 0)
        dl = ImageDraw.Draw(land)
        polys = [r for r in _features(f"ne_{detail}_land") if visible(r)]
        for rings in polys:
            dl.polygon([self._to_base(*p) for p in rings[0]], fill=255)
            for hole in rings[1:]:
                dl.polygon([self._to_base(*p) for p in hole], fill=0)
        lakes = [r for r in _features(f"ne_{detail}_lakes") if visible(r)]
        for rings in lakes:
            dl.polygon([self._to_base(*p) for p in rings[0]], fill=0)

        mask = np.asarray(land, np.float32) / 255.0
        # coastal shading: the sea darkens towards the shore, like an engraved atlas
        small = land.resize((max(1, bw // 6), max(1, bh // 6)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5))
        near = np.asarray(small.resize((bw, bh), Image.BILINEAR), np.float32) / 255.0
        sea = np.array(SEA, np.float32) - (near * (1 - mask))[..., None] * 22
        img = sea * (1 - mask[..., None]) + np.array(LAND, np.float32) * mask[..., None]
        rng = np.random.default_rng(11)
        grain = rng.normal(0, 1, (bh // 3 + 1, bw // 3 + 1)).astype(np.float32)
        grain = np.asarray(Image.fromarray(((grain * 20) + 128).clip(0, 255).astype(np.uint8)).resize((bw, bh), Image.BICUBIC), np.float32)
        img += ((grain - 128) * 0.12)[..., None]
        base = Image.fromarray(img.clip(0, 255).astype(np.uint8), "RGB")

        d = ImageDraw.Draw(base, "RGBA")
        zf = self.ppu * (self.end[2] - self.end[0]) / self.W     # base pixels per frame pixel at the final view
        line = max(2, int(self.H * 0.0022 * zf))
        # sea hatching (sparse horizontal strokes, only on water)
        step = max(6, int(self.H * 0.014 * zf))
        hatch = Image.new("L", (bw, bh), 0)
        hd = ImageDraw.Draw(hatch)
        for y in range(0, bh, step):
            hd.line((0, y, bw, y), fill=40, width=1)
        hatch = Image.fromarray((np.asarray(hatch, np.float32) * (1 - mask)).astype(np.uint8))
        base.paste(Image.new("RGB", (bw, bh), INK), (0, 0), hatch)
        for rings in polys:
            d.line([self._to_base(*p) for p in rings[0]] + [self._to_base(*rings[0][0])], fill=INK + (235,), width=line, joint="curve")
        for rings in lakes:
            d.line([self._to_base(*p) for p in rings[0]] + [self._to_base(*rings[0][0])], fill=INK + (200,), width=max(1, line - 1))
        rivers = [r for r in _features(f"ne_{detail}_rivers_lake_centerlines") if visible(r)]
        for rings in rivers:
            d.line([self._to_base(*p) for p in rings[0]], fill=RIVER + (210,), width=max(1, line - 1), joint="curve")

        # atlas-style region names: wide-spaced italic-free caps in faded ink
        reg_font = _font(self.fonts_dir, max(14, int(self.H * 0.034 * zf)))
        for r in self.spec.get("regions", []):
            x, y = self._to_base(*merc(r["lon"], r["lat"]))
            text = " ".join(r["name"].upper())
            b = d.textbbox((0, 0), text, font=reg_font)
            d.text((x - (b[2] - b[0]) / 2, y - (b[3] - b[1]) / 2), text, font=reg_font, fill=INK + (120,))
        return base

    # ------------------------------------------------------------------ per frame
    def _route_pts(self, view) -> list[tuple[float, float]]:
        vx0, vy0, vx1, vy1 = view
        sx, sy = self.W / (vx1 - vx0), self.H / (vy1 - vy0)
        pts = []
        for lon, lat in self.spec.get("route", []):
            x, y = merc(lon, lat)
            pts.append(((x - vx0) * sx, (vy1 - y) * sy))
        return pts

    def frame(self, t: float) -> Image.Image:
        view = self.view_at(t)
        bx0, by1 = self._to_base(view[0], view[1])
        bx1, by0 = self._to_base(view[2], view[3])
        frame = self.base.resize((self.W, self.H), Image.BICUBIC, box=(bx0, by0, bx1, by1)).convert("RGBA")

        ss = 2                                            # supersampled vector layer for smooth lines
        layer = Image.new("RGBA", (self.W * ss, self.H * ss), (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        pts = [(x * ss, y * ss) for x, y in self._route_pts(view)]
        if len(pts) >= 2:
            rs, re_ = self.route_window()
            prog = _ease((t - rs) / (re_ - rs)) if t > rs else 0.0
            if prog > 0:
                seg = [math.dist(a, b) for a, b in zip(pts, pts[1:])]
                total = sum(seg) or 1.0
                want = total * prog
                drawn = [pts[0]]
                acc = 0.0
                for (a, b), L in zip(zip(pts, pts[1:]), seg):
                    if acc + L >= want:
                        k = (want - acc) / L if L else 1
                        drawn.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
                        break
                    drawn.append(b)
                    acc += L
                w = max(4, int(self.H * 0.0075)) * ss
                # dashed ink route on a pale halo
                d.line(drawn, fill=PAPER + (200,), width=w * 2, joint="curve")
                dash, gap = w * 3, w * 2
                run, on = 0.0, True
                for a, b in zip(drawn, drawn[1:]):
                    L = math.dist(a, b)
                    pos = 0.0
                    while pos < L:
                        limit = dash if on else gap
                        step = min(limit - run, L - pos)
                        p0 = (a[0] + (b[0] - a[0]) * pos / L, a[1] + (b[1] - a[1]) * pos / L) if L else a
                        p1 = (a[0] + (b[0] - a[0]) * (pos + step) / L, a[1] + (b[1] - a[1]) * (pos + step) / L) if L else b
                        if on:
                            d.line((p0, p1), fill=SEAL + (255,), width=w)
                        pos += step
                        run += step
                        if run >= limit - 1e-6:
                            run, on = 0.0, not on
                hx, hy = drawn[-1]
                r = w * 1.4
                d.ellipse((hx - r, hy - r, hx + r, hy + r), fill=SEAL + (255,), outline=INK + (255,), width=max(2, w // 3))

        vx0, vy0, vx1, vy1 = view
        sx, sy = self.W / (vx1 - vx0), self.H / (vy1 - vy0)
        labels = []
        for p, at in zip(self.spec.get("places", []), self.place_times):
            if t < at:
                continue
            k = _ease_out_back((t - at) / 0.35)
            x, y = merc(p["lon"], p["lat"])
            px, py = (x - vx0) * sx * ss, (vy1 - y) * sy * ss
            r = self.H * 0.012 * ss * k
            if r <= 0.5:
                continue
            d.ellipse((px - r * 1.7, py - r * 1.7, px + r * 1.7, py + r * 1.7), fill=SEAL + (60,))
            d.ellipse((px - r, py - r, px + r, py + r), fill=SEAL + (255,), outline=INK + (255,), width=max(2, int(r * 0.3)))
            d.ellipse((px - r * 0.35, py - r * 0.35, px + r * 0.35, py + r * 0.35), fill=PAPER + (255,))
            labels.append((p["name"], px / ss, py / ss, min(1.0, (t - at) / 0.25)))
        frame.alpha_composite(layer.resize((self.W, self.H), Image.LANCZOS))

        placed: list[tuple[float, float, float, float]] = []
        for name, px, py, a in labels:                      # parchment label cards beside each pin, never overlapping
            b = ImageDraw.Draw(frame).textbbox((0, 0), name, font=self.label_font)
            tw, th = b[2] - b[0], b[3] - b[1]
            padx, pady = int(th * 0.6), int(th * 0.4)
            cw, ch = tw + 2 * padx, th + 2 * pady
            off = self.H * 0.024
            options = [(px + off, py - ch / 2), (px - off - cw, py - ch / 2), (px + off, py - off - ch),
                       (px + off, py + off), (px - off - cw, py - off - ch), (px - off - cw, py + off)]
            x, y = options[0]
            for ox, oy in options:
                ox = min(max(10, ox), self.W - cw - 10)
                oy = min(max(10, oy), self.H - ch - 10)
                if not any(ox < r[2] and ox + cw > r[0] and oy < r[3] and oy + ch > r[1] for r in placed):
                    x, y = ox, oy
                    break
            placed.append((x - 4, y - 4, x + cw + 4, y + ch + 4))
            card = Image.new("RGBA", (cw + 6, ch + 6), (0, 0, 0, 0))
            cd = ImageDraw.Draw(card)
            cd.rounded_rectangle((5, 5, cw + 5, ch + 5), int(ch * 0.25), fill=(0, 0, 0, 60))
            cd.rounded_rectangle((0, 0, cw, ch), int(ch * 0.25), fill=PAPER + (255,), outline=INK + (255,), width=max(2, th // 12))
            cd.text((padx - b[0], pady - b[1]), name, font=self.label_font, fill=INK + (255,))
            if a < 1:
                card.putalpha(card.split()[-1].point(lambda v: int(v * a)))
            frame.alpha_composite(card, (int(x), int(y)))
        return frame

    def preview(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.frame(self.d).convert("RGB").save(path)
        return path

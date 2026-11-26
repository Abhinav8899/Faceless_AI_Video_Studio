"""Automatic quality report and review sheets for a run.

review(run_dir) works on partial runs too (e.g. after `--until images`), so a human or an AI
overseer can approve the images before the slow video steps.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.ffmpeg import ffprobe_duration, ffprobe_json


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _sheet(tiles: list[tuple[str, Image.Image]], out: Path, cols: int = 4, tw: int = 480) -> Path | None:
    if not tiles:
        return None
    th = int(tw * 9 / 16)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 26)), (245, 240, 228))
    d = ImageDraw.Draw(sheet)
    f = _font(15)
    for i, (label, im) in enumerate(tiles):
        im = im.convert("RGB").copy(); im.thumbnail((tw - 6, th - 4))
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        sheet.paste(im, (x + (tw - im.width) // 2, y + 24))
        d.text((x + 4, y + 4), label[:60], fill=(40, 30, 20), font=f)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=86)
    return out


def _frame_at(video: Path, t: float) -> Image.Image | None:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0, t):.3f}", "-i", str(video), "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
    if not raw:
        return None
    from io import BytesIO
    return Image.open(BytesIO(raw))


def _detect(final: Path, filt: str, pattern: str) -> list[tuple[float, float]]:
    err = subprocess.run(["ffmpeg", "-v", "info", "-i", str(final), "-vf" if "black" in filt else "-af", filt,
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    return [(float(a), float(b)) for a, b in re.findall(pattern, err)]


def loudness(final: Path) -> float | None:
    err = subprocess.run(["ffmpeg", "-v", "info", "-i", str(final), "-af", "ebur128", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    return float(m[-1]) if m else None


def review(run_dir: Path) -> dict:
    """Build review/ sheets and report.json/report.md. Returns the report dict."""
    run_dir = Path(run_dir)
    script = json.loads((run_dir / "script.json").read_text())
    manifest = json.loads((run_dir / "manifest.json").read_text()) if (run_dir / "manifest.json").is_file() else {}
    out = run_dir / "review"
    out.mkdir(exist_ok=True)
    rep: dict = {"project": script["project"], "checks": [], "warnings": [], "scenes": []}

    image_tiles, frame_tiles = [], []
    for sc in script["scenes"]:
        sid, typ = sc["id"], sc.get("type", "wan")
        st = manifest.get("scenes", {}).get(sid, {}).get("stages", {})
        row = {"id": sid, "type": typ, "audio_s": st.get("audio", {}).get("duration"),
               "status": {k: v.get("status") for k, v in st.items()}}
        img = run_dir / "images" / f"scene_{sid}.png"
        if img.is_file():
            image_tiles.append((f"{sid} [{typ}] {(sc.get('image_prompt') or sc.get('edit_prompt') or '')[:40]}", Image.open(img)))
        vid = run_dir / "composed" / f"scene_{sid}.mp4"
        if not vid.is_file():
            vid = run_dir / "scenes" / f"scene_{sid}.mp4"
        if vid.is_file():
            dur = ffprobe_duration(vid)
            row["shot_s"] = round(dur, 2)
            for frac in (0.15, 0.85) if typ != "still" else (0.5,):
                fr = _frame_at(vid, dur * frac)
                if fr is not None:
                    frame_tiles.append((f"{sid} [{typ}] @{dur * frac:.1f}s", fr))
        if row.get("audio_s") and row["audio_s"] < 1.8:
            rep["warnings"].append(f"scene {sid}: only {row['audio_s']:.1f} s long")
        like = st.get("images", {}).get("likeness")
        if like:
            row["likeness"] = like.get("worst")
            if like.get("passed") is False:
                low = ", ".join(f"{k} {v.get('score') if v.get('score') is not None else v.get('status')}"
                                for k, v in (like.get("scores") or {}).items())
                rep["warnings"].append(f"scene {sid}: subject may not match its portrait after {like.get('attempts')} "
                                       f"tries ({low}); look at it and redo with --only-scene {sid} --force if needed")
        rep["scenes"].append(row)

    from pipeline.subjects import portraits_sheet
    sheets = {
        "images": _sheet(image_tiles, out / "images_sheet.jpg"),
        "frames": _sheet(frame_tiles, out / "frames_sheet.jpg"),
        "subjects": portraits_sheet(script, run_dir, out / "subjects_sheet.jpg"),
    }
    rep["sheets"] = {k: str(v) for k, v in sheets.items() if v}

    final = run_dir / "final.mp4"
    if final.is_file():
        info = ffprobe_json(final)
        v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
        a = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
        dur = float(info["format"]["duration"])
        expected = sum((manifest.get("render", {}).get("scenes") or {}).values())
        rep["final"] = {"path": str(final), "duration_s": round(dur, 2), "width": v.get("width"),
                        "height": v.get("height"), "fps": v.get("r_frame_rate"), "audio": bool(a)}
        def check(name, ok, detail):
            rep["checks"].append({"check": name, "ok": bool(ok), "detail": detail})
        check("resolution 1920x1080", (v.get("width"), v.get("height")) == (1920, 1080), f"{v.get('width')}x{v.get('height')}")
        check("audio track", a is not None, "present" if a else "missing")
        check("length matches scenes", abs(dur - expected) < 0.5 if expected else True, f"{dur:.2f}s vs {expected:.2f}s")
        lufs = loudness(final)
        check("loudness -19..-13 LUFS (YouTube-ready)", lufs is not None and -19 <= lufs <= -13, f"{lufs} LUFS")
        black = _detect(final, "blackdetect=d=0.3:pix_th=0.10", r"black_start:([\d.]+) black_end:([\d.]+)")
        check("no black frames", not black, f"{len(black)} segment(s) {black[:3]}")
        silence = [(s, e) for s, e in _detect(final, "silencedetect=n=-45dB:d=1.6",
                                              r"silence_start: ([\d.]+)[\s\S]*?silence_end: ([\d.]+)")]
        check("no long silences (>1.6 s)", not silence, f"{len(silence)} gap(s) {[(round(s, 1), round(e, 1)) for s, e in silence[:3]]}")
        # one frame from the middle of every scene of the final cut
        t, tiles = 0.0, []
        for sc in script["scenes"]:
            d = (manifest.get("render", {}).get("scenes") or {}).get(sc["id"])
            if d:
                fr = _frame_at(final, t + d / 2)
                if fr is not None:
                    tiles.append((f"{sc['id']} @{t + d / 2:.1f}s", fr))
                t += d
        cs = _sheet(tiles, out / "final_contact_sheet.jpg", cols=5, tw=384)
        if cs:
            rep["sheets"]["final"] = str(cs)

    rep["passed"] = all(c["ok"] for c in rep["checks"]) if rep["checks"] else None
    (out / "report.json").write_text(json.dumps(rep, indent=2))
    lines = [f"# Quality report: {rep['project']}", ""]
    if "final" in rep:
        f = rep["final"]
        lines += [f"Video: {f['duration_s']} s, {f['width']}x{f['height']}, audio {'yes' if f['audio'] else 'NO'}", ""]
        lines += [f"- [{'x' if c['ok'] else ' '}] {c['check']}: {c['detail']}" for c in rep["checks"]] + [""]
    if rep["warnings"]:
        lines += ["Warnings:"] + [f"- {w}" for w in rep["warnings"]] + [""]
    lines += ["| scene | type | audio s | shot s | likeness | stages |", "|---|---|---|---|---|---|"]
    for r in rep["scenes"]:
        lines.append(f"| {r['id']} | {r['type']} | {r.get('audio_s') or '-'} | {r.get('shot_s') or '-'} | "
                     f"{r['likeness'] if r.get('likeness') is not None else '-'} | "
                     + ", ".join(f"{k}:{v}" for k, v in r["status"].items()) + " |")
    lines += ["", "Review sheets: " + ", ".join(Path(p).name for p in rep["sheets"].values())]
    (out / "report.md").write_text("\n".join(lines) + "\n")
    return rep

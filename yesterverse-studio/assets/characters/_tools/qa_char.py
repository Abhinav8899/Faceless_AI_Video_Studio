"""QA for one character: colour drift vs model + large face-crop sheets per pose group.
usage: qa_char.py <char_dir> <out_prefix>"""
import sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw

cdir, prefix = Path(sys.argv[1]), sys.argv[2]


def fg_stats(path):
    a = np.asarray(Image.open(path).convert("RGB").resize((220, 292)), dtype=np.float32)
    bg = np.median(np.concatenate([a[:6].reshape(-1, 3), a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)]), axis=0)
    mask = np.abs(a - bg).sum(-1) > 40
    px = a[mask]
    return px.mean(0), np.median(px, 0), mask


ref_mean, _, _ = fg_stats(cdir / "model.png")
files = sorted((cdir / "turnaround").glob("*.png")) + sorted((cdir / "poses").rglob("*.png"))
rows = []
for f in files:
    m, _, mask = fg_stats(f)
    drift = float(np.abs(m - ref_mean).max())
    ys, xs = np.nonzero(mask)
    rows.append((f, drift, (xs.min(), ys.min(), xs.max(), ys.max())))
print("colour drift vs model (max channel diff of mean fg colour), worst 12:")
for f, d, _ in sorted(rows, key=lambda r: -r[1])[:12]:
    print(f"  {d:5.1f}  {f.relative_to(cdir)}")

# face crops: top 40% of the character's bounding box, large, grouped
groups = {}
for f, d, (x0, y0, x1, y1) in rows:
    rel = f.relative_to(cdir)
    g = rel.parts[1] if rel.parts[0] == "poses" and rel.parts[1].startswith("talk_") else (
        "turnaround" if rel.parts[0] == "turnaround" else "action")
    groups.setdefault(g, []).append((f, d, (x0, y0, x1, y1)))
for g, items in groups.items():
    T, cols = 210, 9
    n = len(items)
    sheet = Image.new("RGB", (cols * T, ((n + cols - 1) // cols) * (T + 28)), "white")
    dr = ImageDraw.Draw(sheet)
    for i, (f, d, (x0, y0, x1, y1)) in enumerate(items):
        im = Image.open(f).convert("RGB")
        sx, sy = im.width / 220, im.height / 292
        h = (y1 - y0) * 0.42
        cx = (x0 + x1) / 2
        box = (int((cx - h * 0.8) * sx), int(y0 * sy) - 4, int((cx + h * 0.8) * sx), int((y0 + h) * sy))
        if g == "action":
            box = (int(x0 * sx), int(y0 * sy), int(x1 * sx), int(y1 * sy))
        c = im.crop(box); c.thumbnail((T - 6, T - 6))
        x, y = (i % cols) * T, (i // cols) * (T + 28)
        sheet.paste(c, (x + (T - c.width) // 2, y + 26))
        lab = str(f.relative_to(cdir)).replace("poses/", "").replace(".png", "")
        dr.text((x + 3, y + 2), lab[:34], fill="black")
        dr.text((x + 3, y + 13), f"drift {d:.0f}", fill=(180, 0, 0) if d > 18 else (90, 90, 90))
    sheet.save(f"{prefix}_{g}.jpg", quality=88)
    print("sheet", g, n)

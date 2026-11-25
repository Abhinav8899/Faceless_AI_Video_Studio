"""One labelled contact sheet of every image for a character (raw images, grey background).
usage: review_sheet.py <char_dir> <out.jpg>"""
import sys
from pathlib import Path
from PIL import Image, ImageDraw

cdir, out = Path(sys.argv[1]), sys.argv[2]
files = [cdir / "model.png"] + sorted((cdir / "turnaround").glob("*.png")) + sorted(
    p for p in (cdir / "poses").rglob("*.png"))
T, cols = 230, 10
rows = (len(files) + cols - 1) // cols
sheet = Image.new("RGB", (cols * T, rows * (T + 16)), "white")
d = ImageDraw.Draw(sheet)
for i, f in enumerate(files):
    im = Image.open(f).convert("RGB"); im.thumbnail((T - 4, T - 4))
    x, y = (i % cols) * T, (i // cols) * (T + 16)
    sheet.paste(im, (x + (T - im.width) // 2, y + 16))
    label = str(f.relative_to(cdir)).replace("poses/", "").replace("turnaround/", "turn/").replace(".png", "")
    d.text((x + 3, y + 2), label[:38], fill="black")
sheet.save(out, quality=86)
print(out, len(files), "images")

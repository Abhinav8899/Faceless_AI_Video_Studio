"""Post-process a character library: transparent cut-outs, index.json, per-character review sheets, README.

usage: charlib_post.py <library_root>/<style>     (needs: pip install -e ".[characters]")

cutouts/<same tree>.png  RGBA, cropped to the character, plus 24 px transparent margin
index.json               every image with: character, kind, pose, view, expression, mouth, size,
                         cutout path and feet anchor (bottom-centre of the alpha mask, in cutout pixels)
sheets/<char>_*.jpg      contact sheets for review
"""
import json, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
from rembg import new_session, remove

root = Path(sys.argv[1])
sess = new_session("isnet-anime")
MARGIN = 24
index = {"style_dir": str(root), "characters": {}}
style_file = root.parent / "_tools" / "style_parchment.txt"

for cdir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in ("cutouts", "sheets")):
    entries = []
    for src in sorted(cdir.rglob("*.png")):
        rel = src.relative_to(cdir)
        if rel.parts[0] == "cutouts":
            continue
        out = cdir / "cutouts" / rel
        if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
            im = remove(Image.open(src).convert("RGB"), session=sess, post_process_mask=True)
            a = np.array(im.split()[-1])
            a[a < 16] = 0                       # drop faint matte noise (e.g. soft floor shadow)
            im.putalpha(Image.fromarray(a))
            bbox = im.getbbox()
            im = im.crop(bbox)
            canvas = Image.new("RGBA", (im.width + 2 * MARGIN, im.height + 2 * MARGIN), (0, 0, 0, 0))
            canvas.paste(im, (MARGIN, MARGIN))
            out.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(out)
        cut = Image.open(out)
        alpha = np.array(cut.split()[-1]) > 64
        ys, xs = np.nonzero(alpha)
        bottom = ys.max()
        feet_x = int(xs[ys >= bottom - 12].mean())
        parts = rel.with_suffix("").parts
        e = {"file": str(rel), "cutout": str(out.relative_to(cdir)), "size": list(cut.size),
             "feet_anchor": [feet_x, int(bottom)]}
        if parts[0] == "turnaround":
            e.update(kind="turnaround", view=parts[1])
        elif parts[0] == "poses":
            expr, mouth = parts[2].rsplit("_", 1)
            e.update(kind="pose", pose=parts[1], expression=expr, mouth=mouth)
        else:
            e.update(kind="model")
        entries.append(e)
    index["characters"][cdir.name] = entries
    print(cdir.name, len(entries), "images", flush=True)

(root / "index.json").write_text(json.dumps(index, indent=1))

# review sheets: one per character per group
sheets = root / "sheets"
sheets.mkdir(exist_ok=True)
for name, entries in index["characters"].items():
    groups = {}
    for e in entries:
        key = e.get("pose") or e["kind"]
        groups.setdefault(key, []).append(e)
    for key, es in groups.items():
        T = 300
        cols = min(6, len(es))
        rows = (len(es) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * T, rows * (T + 18)), (236, 228, 210))
        d = ImageDraw.Draw(sheet)
        for i, e in enumerate(es):
            im = Image.open(root / name / e["cutout"]); im.thumbnail((T - 10, T - 10))
            x, y = (i % cols) * T, (i // cols) * (T + 18)
            sheet.paste(im, (x + (T - im.width) // 2, y + 18 + (T - im.height) // 2), im)
            d.text((x + 4, y + 3), Path(e["file"]).stem if e["kind"] != "turnaround" else e["view"], fill="black")
        sheet.save(sheets / f"{name}__{key}.jpg", quality=85)

counts = {n: len(es) for n, es in index["characters"].items()}
readme = f"""# Character library: {root.name}

Style prompt: `{style_file.read_text().strip() if style_file.exists() else '(see _tools)'}`

## Layout (per character)

    <character>/
      model.png                         canonical design, the identity anchor for everything else
      turnaround/<view>.png             front, three_quarter_left/right, profile_left/right, back
      poses/<pose>/<expression>_<mouth>.png
                                        mouth = closed | open; open is made FROM closed, so swapping
                                        closed/open moves only the mouth (talking flap)
      cutouts/<same tree>.png           transparent, cropped, 24 px margin; use these for compositing

Dialogue poses (talk_front, talk_left, talk_right) have every expression:
neutral, happy, laughing, smug, angry, sad, scared, shocked, thinking.
Each expression is edited FROM that pose's neutral image, so the body stays put when switching.

Action poses have one fitting expression (closed + open): point_right, point_left, idea_finger_up,
arms_crossed, hands_on_hips, shrug, cheer, cower, walk_right, run_right, sit, bow, read_scroll.
Left-facing versions of walk/run can be made by mirroring. Poses where a hand touches the face
(facepalm, hand on chin) are deliberately left out: the image model mangles them, so those moments
are left to Wan video generation.

`index.json` lists every image with its pose/expression/mouth, cutout path and feet anchor
(bottom-centre of the character in cutout pixels), for the compositor to place characters on the ground.
`sheets/` has contact sheets for review. `manifest.json` records the parent, seed and prompt of
every generated image, so any one image can be regenerated.

Images per character: {json.dumps(counts)}

## Regenerate
    cd <repo>/assets/characters
    rm library/<char>/poses/<pose>/<expr>_closed.png   # (and its _open.png)
    ../../.venv/bin/python _tools/charlib.py . library --style-file _tools/style_parchment.txt --chars <char>
    ../../.venv/bin/python _tools/charlib_post.py library
"""
(root / "README.md").write_text(readme)
print("done")

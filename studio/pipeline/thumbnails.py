"""Three YouTube thumbnails per video (1280x720 JPEG): generated picture + optional mascot + big text.

If the script has no meta.thumbnails, three fallbacks are made from the video's own scene images.
"""
from __future__ import annotations

import json
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from pipeline.comfy import ComfyClient
from pipeline.compose import Library, build_rig
from pipeline.config import Config
from pipeline.execution import run_job
from pipeline.runpaths import comfy_dir
from pipeline.script import Script, Thumbnail
from pipeline.stages.common import patch_flux_models, set_image_prompt
from pipeline.workflows import Workflow

TW, TH = 1280, 720
YELLOW, WHITE, INK = (255, 214, 64), (255, 250, 240), (25, 18, 12)


def _font(config: Config, size: int) -> ImageFont.FreeTypeFont:
    for name in ("Bangers-400.woff", "Cinzel-700.woff"):
        p = config.compose.fonts_dir / name
        if p.is_file():
            return ImageFont.truetype(str(p), size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


def _cover(im: Image.Image) -> Image.Image:
    s = max(TW / im.width, TH / im.height)
    im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
    x, y = (im.width - TW) // 2, (im.height - TH) // 2
    return im.crop((x, y, x + TW, y + TH))


def _generate(config: Config, client: ComfyClient, prompt: str, seed: int, out: Path, project: str, idx: int) -> Path:
    wf = Workflow.load(config.workflows.path(config.paths.workflows_dir, "image"), "image")
    patch_flux_models(wf, config)
    set_image_prompt(wf, prompt)
    wf.set("PrimitiveInt", "value", 1920, title_contains="Width")
    wf.set("PrimitiveInt", "value", 1088, title_contains="Height")
    wf.set("RandomNoise", "noise_seed", seed)
    wf.set_save_prefix(f"{comfy_dir(config, project)}/thumbnails/thumb_{idx}")
    run_job(client, wf, out, config.timeouts.image)
    return out


def _paste_character(base: Image.Image, library: Library, c) -> str:
    """Big upper-body mascot with a white sticker outline. Returns the side it occupies."""
    rig = build_rig(library, c.name, c.pose, int(TH * 1.35), c.side == "left")
    sprite = rig.frame(c.expression, "open" if c.expression in ("shocked", "laughing", "scared", "angry") else "closed")
    alpha = sprite.split()[-1]
    halo = Image.new("RGBA", sprite.size, WHITE + (0,))
    halo.putalpha(alpha.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(1.5)))
    shadow = Image.new("RGBA", sprite.size, (0, 0, 0, 0))
    shadow.putalpha(alpha.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(14)).point(lambda v: v * 0.55))
    cx = TW * (0.80 if c.side == "right" else 0.20)
    x = int(cx - rig.feet[0])
    y = int(TH * 1.30 - rig.feet[1])            # feet below the frame: upper body fills the height
    for layer, off in ((shadow, (10, 12)), (halo, (0, 0)), (sprite, (0, 0))):
        base.alpha_composite(layer, (x + off[0], y + off[1]))
    return c.side


def _draw_text(base: Image.Image, config: Config, text: str, position: str) -> None:
    if not text.strip():
        return
    text = text.upper()
    box_w = TW * (0.9 if position in ("top", "bottom") else 0.56)
    words = text.split()
    # candidate layouts: one line, or two lines split at a word boundary (never inside a word)
    layouts = [[text]] + [[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))]
    best, size = [text], 60
    if position in ("top", "bottom"):
        # a banner across the picture: keep it to one line as long as it stays big, so it covers less of the image
        font = _font(config, 104)
        if font.getlength(text) <= box_w:
            layouts = [[text]]
    for s in range(200, 59, -4):
        font = _font(config, s)
        fitting = [lay for lay in layouts if max(font.getlength(line) for line in lay) <= box_w]
        if fitting:
            # prefer the most balanced layout at the biggest size that fits
            best = min(fitting, key=lambda lay: max(font.getlength(line) for line in lay))
            size = s
            break
    lines = best
    font = _font(config, size)
    stroke = max(6, size // 12)
    heights = [font.getbbox(line)[3] - font.getbbox(line)[1] for line in lines]
    gap = int(size * 0.12)
    total = sum(heights) + gap * (len(lines) - 1)
    margin = int(TH * 0.07)
    if position in ("bottom", "bottom_left", "bottom_right"):
        y = TH - margin - total
    elif position == "top":
        y = margin
    else:
        y = (TH - total) // 2 - int(TH * 0.08)
    d = ImageDraw.Draw(base)
    for i, (line, h) in enumerate(zip(lines, heights)):
        w = font.getlength(line)
        x = {"left": margin, "bottom_left": margin, "right": TW - margin - w,
             "bottom_right": TW - margin - w}.get(position, (TW - w) / 2)
        top = font.getbbox(line)[1]
        fill = YELLOW if i == 0 else WHITE
        d.text((x + 8, y - top + 10), line, font=font, fill=(0, 0, 0, 170), stroke_width=stroke, stroke_fill=(0, 0, 0, 170))
        d.text((x, y - top), line, font=font, fill=fill, stroke_width=stroke, stroke_fill=INK)
        y += h + gap


def _compose(config: Config, picture: Path, t: Thumbnail, library: Library | None, out: Path) -> Path:
    base = _cover(Image.open(picture).convert("RGB"))
    base = ImageEnhance.Contrast(ImageEnhance.Color(base).enhance(1.25)).enhance(1.12).convert("RGBA")
    side = None
    if t.character and library is not None:
        side = _paste_character(base, library, t.character)
    position = default_text_position(t) if t.text_position is None else t.text_position
    _draw_text(base, config, t.text, position)
    base.convert("RGB").save(out, "JPEG", quality=90, optimize=True)
    if out.stat().st_size > 2_000_000:                      # YouTube limit is 2 MB
        base.convert("RGB").save(out, "JPEG", quality=80, optimize=True)
    return out


def _fallbacks(script: Script, run_dir: Path) -> list[tuple[Thumbnail, Path]]:
    """No meta.thumbnails: use the first, middle and a late still scene with the project name as text."""
    stills = [s for s in script.scenes if s.type in ("still", "wan") and (run_dir / "images" / f"scene_{s.id}.png").is_file()]
    picks = [stills[0], stills[len(stills) // 2], stills[-1]] if len(stills) >= 3 else stills
    title = script.project.replace("-", " ")[:32]
    return [(Thumbnail(description=f"scene {s.id} with the video title", concept="fallback", image_prompt="-",
                       text=title if i == 0 else ""), run_dir / "images" / f"scene_{s.id}.png") for i, s in enumerate(picks)]


SUFFIX = ("YouTube thumbnail composition: one bold focal subject, close-up, exaggerated emotion, strong contrast, "
          "simple uncluttered background")
THING_SUFFIX = ("YouTube thumbnail composition: one bold focal subject filling the frame, dramatic angle and lighting, "
                "strong contrast, simple uncluttered background, no people")


def default_text_position(t: Thumbnail) -> str:
    """With a mascot, text goes in the bottom corner opposite it: the picture's subject usually ends up in the
    middle, so a full-height text block on the free side would cover its face."""
    if t.character:
        return "bottom_left" if t.character.side == "right" else "bottom_right"
    return "bottom"


def _thumb_prompt(config: Config, t: Thumbnail, style: str) -> str:
    room = []
    if t.character:
        room.append(f"empty uncluttered space on the {t.character.side} third of the picture, no people there")
    text_side = t.text_position or default_text_position(t)
    if t.text:
        if text_side.startswith("bottom_"):
            corner = text_side.split("_")[1]
            room.append(f"the lower {corner} corner kept calm and plain, faces in the upper half of the picture")
        elif text_side in ("top", "bottom"):
            keep = "lower" if text_side == "top" else "upper"
            room.append(f"plain sky or wall across the {text_side} quarter of the picture, every person "
                        f"fully inside the {keep} three quarters with their whole head and face visible")
        else:
            room.append(f"calm empty area on the {text_side} side for a title")
    return ", ".join(p for p in [t.image_prompt, SUFFIX, *room, config.style.house, style] if p)


def _compare_sheet(results: list[Path], descriptions: list[str], out: Path) -> Path:
    n = len(results)
    cols = min(3, n)
    rows = (n + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 650 + 10, rows * 480), (245, 240, 228))
    d = ImageDraw.Draw(sheet)
    f = ImageFont.truetype("DejaVuSans.ttf", 15)
    fb = ImageFont.truetype("DejaVuSans-Bold.ttf", 17)
    for i, (p, desc) in enumerate(zip(results, descriptions)):
        x, y = 10 + (i % cols) * 650, (i // cols) * 480
        sheet.paste(Image.open(p).resize((640, 360), Image.LANCZOS), (x, y + 10))
        d.text((x, y + 378), f"Option {i + 1}  ({p.name})", font=fb, fill=(40, 30, 20))
        for j, line in enumerate(textwrap.wrap(desc, 72)[:4]):
            d.text((x, y + 402 + j * 18), line, font=f, fill=(40, 30, 20))
    sheet.save(out, quality=88)
    return out


def make_custom(config: Config, thumb: Thumbnail, out_dir: Path, library: Library | None, style: str = "",
                variants: int = 3, seed: int = 4242, log=print) -> list[Path]:
    """Thumbnails from a description alone (studio thumbnail): `variants` pictures with different seeds,
    each composed with the same text/mascot. Writes thumbnail_N.jpg and thumbnails_compare.jpg to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = _thumb_prompt(config, thumb, style)
    results = []
    with ComfyClient(config.comfy) as client:
        for i in range(1, variants + 1):
            picture = out_dir / f"thumb_{i}_picture.png"
            log(f"variant {i}/{variants}: generating picture (seed {seed + i})")
            _generate(config, client, prompt, seed + i, picture, "_thumbnails", i)
            results.append(_compose(config, picture, thumb, library, out_dir / f"thumbnail_{i}.jpg"))
    (out_dir / "request.json").write_text(json.dumps({"thumbnail": thumb.model_dump(), "style": style,
                                                       "seed": seed, "variants": variants, "prompt": prompt}, indent=1))
    _compare_sheet(results, [f"{thumb.description} (seed {seed + i})" for i in range(1, variants + 1)],
                   out_dir / "thumbnails_compare.jpg")
    return results


def make_thumbnails(config: Config, script: Script, run_dir: Path, library: Library | None, log=print) -> list[Path]:
    out_dir = run_dir / "thumbnails"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    if script.meta and script.meta.thumbnails:
        base_seed = (script.defaults.seed or 1000) + 900
        with ComfyClient(config.comfy) as client:
            from pipeline import subjects as subj
            for i, t in enumerate(script.meta.thumbnails, 1):
                prompt = _thumb_prompt(config, t, script.style)
                picture = out_dir / f"thumb_{i}_picture.png"
                refs = [subj.portrait_path(run_dir, r.id, r.look) for r in t.subjects]
                if refs and not all(p.is_file() for p in refs):
                    log(f"thumbnail {i}: subject portraits missing (run the images stage first); drawing from text")
                    refs = []
                if refs:
                    if all(script.subject(r.id).kind not in subj.LIVING for r in t.subjects):
                        # "exaggerated emotion" makes the model add shocked faces around a ship or machine
                        prompt = prompt.replace(SUFFIX, THING_SUFFIX)
                    rest = prompt[len(t.image_prompt):].lstrip(", ")
                    prompt = subj.scene_prompt(t.image_prompt, t.subjects, script, config, rest, house=False)
                    layout = subj.layout_prompt(t.image_prompt, t.subjects, script, config, rest, house=False)
                key = json.dumps([prompt, t.seed or base_seed + i, [p.stat().st_mtime for p in refs]])
                stamp = out_dir / f"thumb_{i}_picture.key"
                if not (picture.is_file() and stamp.is_file() and stamp.read_text() == key):
                    log(f"thumbnail {i}: generating picture" + (" from subject portraits" if refs else ""))
                    if refs:
                        subj.draw(client, config, prompt, refs, t.seed or base_seed + i, picture,
                                  f"{comfy_dir(config, script.project)}/thumbnails/thumb_{i}", script.project, 1920, 1088,
                                  layout=layout)
                    else:
                        _generate(config, client, prompt, t.seed or base_seed + i, picture, script.project, i)
                    stamp.write_text(key)
                results.append(_compose(config, picture, t, library, out_dir / f"thumbnail_{i}.jpg"))
                log(f"thumbnail {i}: {t.description}")
        thumbs = script.meta.thumbnails
    else:
        log("no meta.thumbnails in the script: making 3 fallback thumbnails from scene images")
        pairs = _fallbacks(script, run_dir)
        for i, (t, picture) in enumerate(pairs, 1):
            results.append(_compose(config, picture, t, library, out_dir / f"thumbnail_{i}.jpg"))
        thumbs = [t for t, _ in pairs]
    _compare_sheet(results, [t.description for t in thumbs], out_dir / "thumbnails_compare.jpg")
    return results

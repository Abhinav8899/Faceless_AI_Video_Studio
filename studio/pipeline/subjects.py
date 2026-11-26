"""Consistent subjects: one reference portrait per subject, every scene that lists it drawn from it.

A subject is anything that must look the same all video long: a person, an animal, a tool,
a machine, a ship, a building. For each one the studio
  1. draws `portrait_candidates` reference portraits (one subject, whole, plain background) and keeps
     the clearest one (or uses the script's own `reference_image`),
  2. draws one extra portrait per named look a scene uses (same subject, other clothes / state),
     made from the main portrait,
  3. draws every scene listing the subject with the FLUX 3 reference workflow, the portraits as
     reference images, and
  4. checks the result automatically (pipeline/likeness.py); a scene that does not match is
     redrawn with a new seed, up to `max_attempts`; the best drawing is kept and flagged.
Portraits live in work/subjects/ and are copied to refs/subjects/<project>/ for reuse.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.execution import run_job
from pipeline.likeness import LikenessChecker
from pipeline.runpaths import comfy_dir
from pipeline.script import Script, Subject, SubjectRef
from pipeline.stages.common import patch_flux_models, resolve_image, set_image_prompt
from pipeline.workflows import Workflow, WorkflowError

LIVING = ("person", "animal", "creature")
IDENTITY = {
    "person": "face, hairstyle, age, skin tone and body build",
    "animal": "face, markings, colours and body build",
    "creature": "face, markings, colours and body shape",
}
THINGS = "shape, proportions, design, colours, materials and details"


def portrait_path(run_dir: Path, sid: str, look: str | None = None) -> Path:
    return run_dir / "subjects" / (f"{sid}__{look}.png" if look else f"{sid}.png")


def look_text(subject: Subject, look: str | None) -> str:
    return subject.looks[look] if look else subject.look


def used_refs(script: Script, scenes=None) -> set[tuple[str, str | None]]:
    """(subject id, look) pairs needed by these scenes and by the thumbnails."""
    scenes = script.scenes if scenes is None else scenes
    refs = {(r.id, r.look) for sc in scenes for r in sc.subjects}
    refs |= {(r.id, r.look) for t in (script.meta.thumbnails if script.meta else []) for r in t.subjects}
    return refs


# ---- prompts ---------------------------------------------------------------------------------
def portrait_prompt(subject: Subject, script: Script, config: Config) -> str:
    noun = subject.detect_noun()
    look = subject.look.strip()
    if subject.kind in LIVING:
        body = (f"Character reference portrait of {subject.name}, {subject.design}" + (f", {look}" if look else "")
                + f". Exactly one {noun}, the whole body from head to feet visible, standing in a relaxed neutral pose "
                  "with arms down at the sides, three-quarter view facing the viewer, centred, with space around it")
    else:
        body = (f"Reference picture of {subject.name}, {subject.design}" + (f", {look}" if look else "")
                + f". Exactly one {noun}, the whole {noun} visible with space around it, three-quarter view, centred")
    parts = [body, "plain flat light parchment background, nothing else in the picture, even soft light",
             script.style.strip(), config.style.house]
    return ". ".join(p.rstrip(". ") for p in parts if p)


def look_prompt(subject: Subject, look: str) -> str:
    noun = subject.detect_noun()
    keep = IDENTITY.get(subject.kind, THINGS)
    return (f"The same {noun} as in image 1 ({subject.name}), now {subject.looks[look]}. Keep exactly the same {keep} "
            f"as in image 1. Exactly one {noun}, whole and centred, neutral pose, plain flat light parchment background, "
            "nothing else in the picture")


def scene_prompt(base: str, refs: list[SubjectRef], script: Script, config: Config, style: str = "",
                 house: bool = True) -> str:
    """The scene text plus, per subject, which reference image it is and what must not change."""
    lines = [base.strip().rstrip(".")]
    for i, ref in enumerate(refs, 1):
        s = script.subject(ref.id)
        noun = s.detect_noun()
        keep = IDENTITY.get(s.kind, THINGS)
        line = f"The {noun} {s.name} is the one in image {i}: exactly the same {keep} as in image {i}"
        look = look_text(s, ref.look)
        if look:
            line += f"; here: {look}"
        lines.append(line)
    lines.append("Use the reference images only for how the subjects look: keep the pose, camera angle and "
                 "background of the scene described, not their plain background")
    return ". ".join(p for p in lines + [style.strip(), config.style.house if house else ""] if p)


def layout_prompt(base: str, refs: list[SubjectRef], script: Script, config: Config, style: str = "",
                  house: bool = True) -> str:
    """Text-only prompt for the layout pass: the scene with each subject's design written out."""
    parts = [base.strip().rstrip(".")]
    for r in refs:
        s = script.subject(r.id)
        look = look_text(s, r.look)
        parts.append(f"The {s.detect_noun()} is {s.name}: {s.design}" + (f", {look}" if look else ""))
    return ". ".join(p for p in parts + [style.strip(), config.style.house if house else ""] if p)


# ---- drawing ---------------------------------------------------------------------------------
def reference_workflow(config: Config, ref_names: list[str], init_name: str | None = None,
                       denoise: float = 1.0) -> Workflow:
    """The FLUX 3 edit graph with one LoadImage per reference image (1-4) feeding ReferenceMultiLatent.
    With `init_name`, sampling starts from that picture (its composition) at `denoise` instead of noise."""
    if not ref_names:
        raise WorkflowError("reference workflow needs at least one image")
    wf = Workflow.load(config.workflows.path(config.paths.workflows_dir, "edit"), "edit")
    patch_flux_models(wf, config)
    rid, ref_node = wf.one("ReferenceMultiLatent")
    for key in [k for k in ref_node["inputs"] if k.startswith("images.")]:
        del ref_node["inputs"][key]
    for node_id, _ in wf.find("LoadImage"):
        del wf.data[node_id]
    for i, name in enumerate(ref_names):
        nid = wf.add_node(f"subject_ref_{i}", "LoadImage", {"image": name}, f"Subject reference {i + 1}")
        ref_node["inputs"][f"images.image{i}"] = [nid, 0]
    if init_name:
        vae_id, _ = wf.one("VAELoader")
        sampler_id, sampler = wf.one("SamplerCustomAdvanced")
        empty = sampler["inputs"]["latent_image"][0]
        wf.add_node("layout_image", "LoadImage", {"image": init_name}, "Layout picture")
        wf.add_node("layout_latent", "VAEEncode", {"pixels": ["layout_image", 0], "vae": [vae_id, 0]}, "Layout latent")
        sampler["inputs"]["latent_image"] = ["layout_latent", 0]
        del wf.data[empty]
        wf.set("BasicScheduler", "denoise", denoise)
    return wf


@dataclass
class Check:
    sid: str
    reference: Path
    noun: str
    person: bool


def draw(client: ComfyClient, config: Config, prompt: str, refs: list[Path], seed: int, dest: Path,
         save_prefix: str, project: str, width: int, height: int, layout: str | None = None):
    """Reference drawing. With `layout` (a text prompt) and subjects.compose_from_text on, a text-only picture
    is drawn first for the composition and the reference pass starts from it; otherwise the reference pass starts
    from noise (which tends to copy the portrait's pose and plain background)."""
    names = [client.upload_image(p, subfolder=f"{comfy_dir(config, project)}/subjects") for p in refs]
    init_name = None
    elapsed = 0.0
    if layout and config.subjects.compose_from_text:
        layout_png = dest.with_name(f"{dest.stem}.layout.png")
        r = _text_draw(client, config, layout, seed, layout_png, f"{save_prefix}_layout", width, height)
        elapsed += r.elapsed
        init_name = client.upload_image(layout_png, subfolder=f"{comfy_dir(config, project)}/subjects")
        layout_png.unlink(missing_ok=True)
    wf = reference_workflow(config, names, init_name, config.subjects.denoise)
    if not init_name:
        wf.set("EmptyFlux2LatentImage", "width", width)
        wf.set("EmptyFlux2LatentImage", "height", height)
    set_image_prompt(wf, prompt)
    wf.set("RandomNoise", "noise_seed", seed)
    wf.set_save_prefix(save_prefix)
    result = run_job(client, wf, dest, config.timeouts.image)
    return result, wf, elapsed + result.elapsed


def _threshold(config: Config, res: dict) -> float:
    return config.subjects.threshold_person if res.get("by") == "head" else config.subjects.threshold_thing


def checked_draw(client: ComfyClient, config: Config, checker: LikenessChecker | None, prompt: str,
                 refs: list[Path], checks: list[Check], seed: int, dest: Path, save_prefix: str, project: str,
                 width: int, height: int, log=print, layout: str | None = None) -> dict:
    """Draw, check every subject, redraw with a new seed when one does not match. Keeps the best try."""
    cfg = config.subjects
    attempts = max(1, cfg.max_attempts) if checker is not None and checker.available else 1
    tries: list[dict] = []
    for a in range(attempts):
        s = seed + a * 7919
        out = dest.with_name(f"{dest.stem}.try{a + 1}.png") if attempts > 1 else dest
        result, wf, elapsed = draw(client, config, prompt, refs, s, out, save_prefix, project, width, height, layout)
        scores, margins = {}, []
        if attempts > 1:
            for c in checks:
                r = checker.score(out, c.reference, c.noun, c.person) or {"status": "error", "score": None}
                if r["status"] == "checked":
                    r["threshold"] = _threshold(config, r)
                    margins.append(r["score"] - r["threshold"])
                elif r["status"] == "not_found":          # the subject is missing from the picture
                    margins.append(-1.0)
                scores[c.sid] = r
        margin = min(margins) if margins else None
        passed = None if margin is None else margin >= 0
        checked = [r["score"] for r in scores.values() if r.get("score") is not None]
        tries.append({"seed": s, "path": out, "scores": scores, "margin": margin, "passed": passed,
                      "worst": min(checked) if checked else None,
                      "elapsed": round(elapsed, 1), "prompt_id": result.prompt_id, "workflow_sha": wf.sha256()})
        detail = ", ".join(f"{k} {v['score'] if v.get('score') is not None else v['status']}" for k, v in scores.items())
        if attempts > 1:
            log(f"  try {a + 1}/{attempts} (seed {s}): {detail or 'nothing to check'}"
                + ("" if passed is None else (" -> match" if passed else " -> below the threshold")))
        if passed is not False:
            break
    best = max(tries, key=lambda t: t["margin"] if t["margin"] is not None else 2.0)   # unchecked = accepted as is
    if best["path"] != dest:
        shutil.copyfile(best["path"], dest)
    for t in tries:
        if t["path"] != dest:
            Path(t["path"]).unlink(missing_ok=True)
    return {"seed": best["seed"], "attempts": len(tries), "passed": best["passed"], "worst": best["worst"],
            "scores": best["scores"], "elapsed": sum(t["elapsed"] for t in tries), "prompt_id": best["prompt_id"],
            "workflow_sha": best["workflow_sha"], "tries": [t["worst"] for t in tries]}


# ---- portraits -------------------------------------------------------------------------------
def _hash(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _text_draw(client: ComfyClient, config: Config, prompt: str, seed: int, dest: Path, prefix: str,
               width: int | None = None, height: int | None = None):
    wf = Workflow.load(config.workflows.path(config.paths.workflows_dir, "image"), "image")
    patch_flux_models(wf, config)
    set_image_prompt(wf, prompt)
    wf.set("PrimitiveInt", "value", width or config.subjects.portrait_size, title_contains="Width")
    wf.set("PrimitiveInt", "value", height or config.subjects.portrait_size, title_contains="Height")
    wf.set("RandomNoise", "noise_seed", seed)
    wf.set_save_prefix(prefix)
    return run_job(client, wf, dest, config.timeouts.image)


def ensure_portraits(config: Config, script: Script, run_dir: Path, manifest, client: ComfyClient,
                     checker: LikenessChecker | None, needed: set[tuple[str, str | None]], log=print,
                     force: bool = False) -> dict[tuple[str, str | None], Path]:
    """Make (or reuse) the portrait of every needed (subject, look). Returns {(id, look): path}."""
    store = manifest.data.setdefault("subjects", {})
    paths: dict[tuple[str, str | None], Path] = {}
    base_seed = (script.defaults.seed or 1000) + 500
    refs_copy = config.paths.refs_dir / "subjects" / script.project
    for n, sid in enumerate(dict.fromkeys(i for i, _ in sorted(needed, key=lambda r: (r[0], r[1] or "")))):
        s = script.subject(sid)
        dest = portrait_path(run_dir, sid)
        prompt = portrait_prompt(s, script, config)
        own = resolve_image(config, s.reference_image) if s.reference_image else None
        key = _hash(prompt, str(own) if own else None, own.stat().st_mtime if own and own.is_file() else None,
                    config.models.flux_unet)
        if force or store.get(sid, {}).get("key") != key or not dest.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if own:
                if not own.is_file():
                    raise FileNotFoundError(f"subject {sid}: reference_image not found: {own}")
                shutil.copyfile(own, dest)
                store[sid] = {"key": key, "path": str(dest.relative_to(run_dir)), "source": str(own)}
                log(f"subject {sid}: using your portrait {own.name}")
            else:
                cands = []
                total = max(1, config.subjects.portrait_candidates)
                for c in range(total):
                    seed = base_seed + n * 101 + c
                    cand = run_dir / "subjects" / "candidates" / f"{sid}_{c + 1}.png"
                    log(f"subject {sid}: portrait {c + 1}/{total} (seed {seed})")
                    _text_draw(client, config, prompt, seed, cand, f"{comfy_dir(config, script.project)}/subjects/{sid}_{c + 1}")
                    info = checker.inspect(cand, s.detect_noun()) if checker is not None and checker.available else None
                    cands.append((info["quality"] if info else -c, seed, cand, info))
                quality, seed, best, info = max(cands, key=lambda t: t[0])
                shutil.copyfile(best, dest)
                store[sid] = {"key": key, "path": str(dest.relative_to(run_dir)), "seed": seed,
                              "picked": best.name, "quality": quality, "prompt": prompt,
                              "candidates": [{"file": c[2].name, "quality": c[0], "detect": c[3]} for c in cands]}
                log(f"subject {sid}: kept {best.name}" + (f" (clearest, quality {quality})" if info else ""))
            for stale in run_dir.glob(f"subjects/{sid}__*.png"):          # looks follow the main portrait
                stale.unlink()
            manifest.save()
        paths[(sid, None)] = dest
    for sid, look in sorted((r for r in needed if r[1]), key=lambda r: (r[0], r[1])):
        s = script.subject(sid)
        dest = portrait_path(run_dir, sid, look)
        prompt = look_prompt(s, look)
        key = _hash(prompt, store[sid]["key"])
        lkey = f"{sid}__{look}"
        if force or store.get(lkey, {}).get("key") != key or not dest.is_file():
            log(f"subject {sid}: portrait for look '{look}'")
            check = [Check(sid, paths[(sid, None)], s.detect_noun(), s.kind == "person")]
            size = config.subjects.portrait_size
            info = checked_draw(client, config, checker, prompt, [paths[(sid, None)]], check,
                                base_seed + 7 + len(lkey), dest, f"{comfy_dir(config, script.project)}/subjects/{lkey}",
                                script.project, size, size, log)
            store[lkey] = {"key": key, "path": str(dest.relative_to(run_dir)), "prompt": prompt,
                           **{k: v for k, v in info.items() if k in ("seed", "attempts", "passed", "worst", "scores")}}
            manifest.save()
        paths[(sid, look)] = dest
    refs_copy.mkdir(parents=True, exist_ok=True)
    for p in paths.values():
        shutil.copyfile(p, refs_copy / p.name)
    return paths


def scene_refs(script: Script, refs: list[SubjectRef], portraits: dict) -> tuple[list[Path], list[Check]]:
    images, checks = [], []
    for r in refs:
        s = script.subject(r.id)
        p = portraits[(r.id, r.look)]
        images.append(p)
        checks.append(Check(r.id, p, s.detect_noun(), s.kind == "person"))
    return images, checks


def portraits_sheet(script: dict, run_dir: Path, out: Path) -> Path | None:
    """Review sheet of all portraits with their names (used by qa.review)."""
    from PIL import Image, ImageDraw, ImageFont
    files = sorted((run_dir / "subjects").glob("*.png"))
    if not files:
        return None
    names = {s["id"]: s["name"] for s in script.get("subjects", [])}
    tw = 300
    cols = min(5, len(files))
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (tw + 40) + 10), (245, 240, 228))
    d = ImageDraw.Draw(sheet)
    font = ImageFont.truetype("DejaVuSans.ttf", 14)
    for i, f in enumerate(files):
        sid, _, look = f.stem.partition("__")
        im = Image.open(f).convert("RGB")
        im.thumbnail((tw, tw))
        x, y = 10 + (i % cols) * (tw + 10), 10 + (i // cols) * (tw + 40)
        sheet.paste(im, (x, y))
        d.text((x, y + tw + 6), f"{names.get(sid, sid)}" + (f" ({look})" if look else ""), font=font, fill=(40, 30, 20))
    sheet.save(out, quality=88)
    return out

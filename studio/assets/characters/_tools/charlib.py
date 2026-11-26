"""Build a character library: model -> poses -> expressions -> mouth-open variants.

Runs on the remote with ~/youtube/studio2/.venv (uses the pipeline's ComfyClient + Workflow and the studio's
edit workflow, FLUX 3 Image Klein since 2026-11-26). The parchment_v1 library was made with FLUX.2 Klein;
a character made now with FLUX 3 may look slightly different, so make all of a new character's images together.

usage: charlib.py <library_root> <style_name> [--chars a,b] [--only turnaround,dialogue,action] [--limit N]

Layout:
  <root>/<style>/<char>/model.png                      canonical model in the style
  <root>/<style>/<char>/turnaround/<view>.png
  <root>/<style>/<char>/poses/<pose>/<expr>_<mouth>.png  mouth = closed | open
  <root>/<style>/<char>/cutouts/...                      same tree, transparent PNGs (separate step)
  <root>/<style>/manifest.json
"""
import argparse, json, sys, time
from pathlib import Path

sys.path.insert(0, str(Path.home() / "youtube" / "studio"))
from pipeline.comfy import ComfyClient          # noqa: E402
from pipeline.config import load_config         # noqa: E402
from pipeline.execution import run_job          # noqa: E402
from pipeline.stages.common import patch_flux_models, set_image_prompt, wire_edit_images  # noqa: E402
from pipeline.workflows import Workflow          # noqa: E402

W, H = 880, 1168
# Do not list example accessories here: the model treats any named item as something to add
# (naming "goggles" put goggles on the apprentice, who has none).
KEEP = ("Keep exactly the same character as in the reference image: same face, hair, headwear and accessories "
        "exactly as shown, without adding or removing any item, same outfit, colors, proportions and drawing style. "
        "Full body visible head to feet, centered, plain light grey background, no shadow, no text.")

CHARACTERS = {
    "sir_grumbold": {"desc": "a stout grumpy old clean-shaven knight with big bushy white eyebrows, a round red nose, grey plate armor and a brown belt",
                      "src": "sir_grumbold/Sir_Grumbold_base_00001_.png"},
    "pip":          {"desc": "a small young boy squire wearing an oversized round iron helmet and a brown tunic with pale shoulder pads",
                      "src": "pip/pip_base_00001_.png"},
    "bumble":       {"desc": "a cheerful round-faced knight in grey armor with a red plume on his helmet",
                      "src": "bumble/bumble_base_00001_.png"},
    "dame_ironwill": {"desc": "a stern female knight with two long dark braids, grey armor and a blue tabard",
                      "src": "ironwill/Dame_Ironwill_base_00001_.png",
                      "extra": "Redesign her proportions to match a simplified chunky cartoon cast: slightly larger head, shorter sturdier body, simple dot-like eyes and a simple face, not anime. Keep her braids, helmet, armor and blue tabard."},
    "lord_vexmoor": {"desc": "a scheming nobleman in black armor with a horned black helmet",
                      "src": "lord_vexmoor/Lord_Vexmoor_base_00001_.png"},
    # channel mascots (time-traveller duo); model.png comes from _tools/mascot_design.py, so no "src"
    "inventor":     {"desc": "a cheerful clean-shaven time-travelling inventor with messy white hair, brass goggles on top of the head, a long teal coat, a brass pocket watch and a leather satchel",
                      "src": None},
    "apprentice":   {"desc": "a curious young apprentice with curly orange hair and freckles, a red vest, an oversized mustard scarf, brown shorts and a glowing blue hourglass gadget on the belt",
                      "src": None},
}

TURNAROUND = {
    "front": "standing facing the viewer, arms relaxed at the sides",
    "three_quarter_left": "standing in three-quarter view turned toward the left side of the image, arms relaxed",
    "three_quarter_right": "standing in three-quarter view turned toward the right side of the image, arms relaxed",
    "profile_left": "standing in full side profile facing the left side of the image, arms relaxed",
    "profile_right": "standing in full side profile facing the right side of the image, arms relaxed",
    "back": ("standing seen from behind, back to the viewer; the back of the head shows exactly the same hair and "
             "headwear as the front view, with no hat or helmet added unless the character already wears one"),
}

# dialogue poses get every expression x {closed, open}
TALK_GESTURE = ("one forearm is raised so the hand is at chest height in front of the body, palm open and turned "
                "upward, fingers relaxed, as if explaining something; the other arm hangs relaxed")
# pose -> (parent image, description)
DIALOGUE = {
    "talk_front": ("turnaround/front.png", f"standing facing the viewer; {TALK_GESTURE}"),
    "talk_left": ("turnaround/three_quarter_left.png", f"standing in three-quarter view turned toward the left side of the image; {TALK_GESTURE}"),
    "talk_right": ("turnaround/three_quarter_right.png", f"standing in three-quarter view turned toward the right side of the image; {TALK_GESTURE}"),
}
EXPRESSIONS = {
    "neutral": "a calm neutral expression",
    "happy": "a warm happy smile",
    "laughing": "laughing heartily with eyes squeezed shut",
    "smug": "a sly smug half-smile with one raised eyebrow, clearly pleased with himself, not angry",
    "angry": "an angry scowl with furrowed brows",
    "sad": "a sad expression with drooping brows",
    "scared": "a frightened expression with wide eyes and trembling",
    "shocked": "a shocked expression with wide eyes and raised brows",
    "thinking": "a thoughtful expression, eyes looking up",
}
# action poses: one fitting expression, closed + open mouth.
# No poses where a hand touches the face (facepalm, hand on chin): the edit model mangles them; use Wan for those.
ACTION = {
    "point_right":   ("pointing firmly toward the right side of the image with one arm extended", "neutral"),
    "point_left":    ("pointing firmly toward the left side of the image with one arm extended", "neutral"),
    "idea_finger_up": ("raising one index finger in the air having a bright idea", "happy"),
    "arms_crossed":  ("standing with arms crossed over the chest", "smug"),
    "hands_on_hips": ("standing confidently with both hands on the hips", "happy"),
    "shrug":         ("shrugging with both palms up and shoulders raised", "neutral"),
    "cheer":         ("cheering with both arms raised high in triumph", "laughing"),
    "cower":         ("cowering, knees bent and arms raised defensively", "scared"),
    "walk_right":    ("walking toward the right side of the image, side view, mid-stride", "neutral"),
    "run_right":     ("running fast toward the right side of the image, side view, dynamic stride", "shocked"),
    "sit":           ("sitting on a plain wooden stool, three-quarter view", "neutral"),
    "bow":           ("bowing politely: upper body bent forward at the waist, head lowered, one hand on the chest, the other arm out to the side", "happy"),
    "read_scroll":   ("holding an open parchment scroll with both hands and reading it", "thinking"),
}


MARGIN = "The whole body, both arms and both hands are fully inside the image with empty margin on every side."
LOCK = "Keep the eyebrows and hair exactly the same color, size and shape as in the image."


def mouth(ep):
    # naming the expression stops the edit from drifting back to the character's default face
    return (f"Change ONLY the mouth: open it as if speaking a word mid-sentence, while keeping {ep}. "
            f"Keep the eyes, eyebrows, the same {ep}, body, pose, position and framing exactly identical. {LOCK} {{style}}")


def expr_edit(ep):
    return (f"Change ONLY the facial expression to {ep}, mouth closed. {LOCK} Keep the body pose, hands, outfit, "
            f"position and framing exactly identical. {{style}}")


def build_jobs(only):
    # (relpath, parent_relpath, ref, size, prompt); ref "model" anchors identity for new poses,
    # ref "self" uses the parent alone so face/mouth edits are not pulled back to the model's expression
    PORTRAIT, SQUARE = (880, 1168), (1168, 1168)
    jobs = []
    if "model" in only:
        jobs.append(("model.png", "@src", "self", PORTRAIT,
                     "Redraw this character, {desc}, standing facing the viewer with arms relaxed, in the target art style. {extra} {style} " + KEEP))
    if "turnaround" in only:
        for v, p in TURNAROUND.items():
            jobs.append((f"turnaround/{v}.png", "model.png", "model", PORTRAIT,
                         f"The character is {p}, neutral expression. {{style}} {KEEP}"))
    if "dialogue" in only:
        for pose, (parent, p) in DIALOGUE.items():
            base = f"poses/{pose}/neutral_closed.png"
            jobs.append((base, parent, "model", PORTRAIT,
                         f"Repose the character: {p}. Calm neutral expression, mouth closed. {{style}} {KEEP} {MARGIN}"))
            for e, ep in EXPRESSIONS.items():
                closed = f"poses/{pose}/{e}_closed.png"
                if e != "neutral":
                    jobs.append((closed, base, "self", PORTRAIT, expr_edit(ep)))
                jobs.append((f"poses/{pose}/{e}_open.png", closed, "self", PORTRAIT, mouth(ep)))
    if "action" in only:
        # pose first with a neutral face (identity anchored on the model), then the expression as its own edit,
        # so the character's default face (e.g. Grumbold's scowl) does not override the requested expression
        for pose, (p, e) in ACTION.items():
            base = f"poses/{pose}/neutral_closed.png"
            jobs.append((base, "model.png", "model", SQUARE,
                         f"Repose the character: {p}. Calm neutral expression, mouth closed. {{style}} {KEEP} {MARGIN}"))
            closed = f"poses/{pose}/{e}_closed.png"
            if e != "neutral":
                jobs.append((closed, base, "self", SQUARE, expr_edit(EXPRESSIONS[e])))
            jobs.append((f"poses/{pose}/{e}_open.png", closed, "self", SQUARE, mouth(EXPRESSIONS[e])))
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root"); ap.add_argument("style_name")
    ap.add_argument("--style-file", required=True, help="text file with the style sentence")
    ap.add_argument("--chars", default=",".join(CHARACTERS))
    ap.add_argument("--only", default="model,turnaround,dialogue,action")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--seed", type=int, default=7001)
    a = ap.parse_args()

    style = Path(a.style_file).read_text().strip()
    cfg = load_config(Path.home() / "youtube" / "studio" / "config.yaml")
    template = Workflow.load(cfg.workflows.path(cfg.paths.workflows_dir, "edit"), "edit")
    root = Path(a.root) / a.style_name
    src_root = Path.home() / "ComfyUI" / "characters"
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"style": style, "characters": {}}
    only = set(a.only.split(","))
    done = 0
    with ComfyClient(cfg.comfy) as client:
        for ci, name in enumerate(a.chars.split(",")):
            ch = CHARACTERS[name]
            cdir = root / name
            entry = manifest["characters"].setdefault(name, {"description": ch["desc"], "images": {}})
            for ji, (rel, parent, refmode, (w, h), prompt) in enumerate(build_jobs(only)):
                out = cdir / rel
                if out.exists():
                    continue
                parent_path = src_root / ch["src"] if parent == "@src" else cdir / parent
                if not parent_path.exists():
                    print(f"skip {name}/{rel}: parent missing {parent}"); continue
                ref_path = cdir / "model.png" if refmode == "model" else parent_path
                wf = template.clone()
                patch_flux_models(wf, cfg)
                b = client.upload_image(parent_path, subfolder=f"charlib/{name}")
                r = client.upload_image(ref_path, subfolder=f"charlib/{name}")
                wire_edit_images(wf, b, r)
                for cls in ("EmptyFlux2LatentImage", "Flux2Scheduler"):
                    if wf.find(cls):                      # Flux2Scheduler only exists in FLUX.2 graphs
                        wf.set(cls, "width", w); wf.set(cls, "height", h)
                text = " ".join(prompt.format(style=style, desc=ch["desc"], extra=ch.get("extra", "")).split())
                set_image_prompt(wf, text)
                seed = a.seed + ci * 1000 + ji
                wf.set("RandomNoise", "noise_seed", seed)
                wf.set_save_prefix(f"charlib/{a.style_name}/{name}/{rel[:-4]}")
                t0 = time.time()
                run_job(client, wf, out, cfg.timeouts.image)
                entry["images"][rel] = {"parent": parent, "seed": seed, "prompt": text}
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(manifest, indent=1))
                done += 1
                print(f"{name}/{rel}  {time.time() - t0:.1f}s", flush=True)
                if a.limit and done >= a.limit:
                    return


if __name__ == "__main__":
    main()

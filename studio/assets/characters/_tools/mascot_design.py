"""Text-to-image candidates for a character design (the studio's image workflow: FLUX 3 Image Klein).

usage (inside the studio folder, ComfyUI running):  .venv/bin/python assets/characters/_tools/mascot_design.py
Write your art style in assets/characters/_tools/style.txt and your characters in DESIGNS below.
Candidates are saved to assets/characters/_candidates/<name>/seed_<n>.png.
"""
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]      # the studio folder
sys.path.insert(0, str(REPO))
from pipeline.comfy import ComfyClient
from pipeline.config import load_config
from pipeline.execution import run_job
from pipeline.stages.common import patch_flux_models, set_image_prompt
from pipeline.workflows import Workflow

root = REPO / "assets" / "characters"
style = (root / "_tools" / "style.txt").read_text().strip()
cfg = load_config(REPO / "config.yaml")
tpl = Workflow.load(cfg.workflows.path(cfg.paths.workflows_dir, "image"), "image")
COMMON = ("Character design sheet of ONE character only, standing facing the viewer, arms relaxed at the sides, "
          "full body head to feet, centered, clearly visible eyes and mouth, nothing covering the eyes or mouth. ")
DESIGNS = {
    # name: full visual description (face, hair, outfit, colours, accessories). Example:
    "host": ("A friendly middle-aged host, round face, short dark hair, round glasses, a green sweater over a white "
             "collar, brown trousers, brown shoes."),
}
out_root = root / "_candidates"
with ComfyClient(cfg.comfy) as c:
    for name, desc in DESIGNS.items():
        out = out_root / name
        out.mkdir(parents=True, exist_ok=True)
        for seed in (11, 22, 33, 44):
            wf = tpl.clone(); patch_flux_models(wf, cfg)
            set_image_prompt(wf, f"{COMMON}{desc} {style}")
            wf.set("PrimitiveInt", "value", 880, title_contains="Width")
            wf.set("PrimitiveInt", "value", 1168, title_contains="Height")
            wf.set("RandomNoise", "noise_seed", seed)
            wf.set_save_prefix(f"{cfg.paths.comfy_subfolder}/charlib/candidates/{name}_{seed}")
            run_job(c, wf, out / f"seed_{seed}.png", cfg.timeouts.image)
            print(name, seed, flush=True)
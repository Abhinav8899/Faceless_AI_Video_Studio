"""Text-to-image candidates for the two time-traveller mascots (FLUX.2 Klein, image workflow)."""
import sys
from pathlib import Path
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
from pipeline.comfy import ComfyClient
from pipeline.config import load_config
from pipeline.execution import run_job
from pipeline.stages.common import patch_flux_models, set_image_prompt
from pipeline.workflows import Workflow

root = REPO / "assets" / "characters"
style = (root / "_tools/style_parchment.txt").read_text().strip()
cfg = load_config(REPO / "config.yaml")
tpl = Workflow.load(cfg.workflows.path(cfg.paths.workflows_dir, "image"), "image")
COMMON = ("Character design sheet of ONE character only, standing facing the viewer, arms relaxed at the sides, "
          "full body head to feet, centered, simplified chunky cartoon proportions with a large head and a short "
          "sturdy body, simple dot-like eyes with white highlights, clearly visible mouth, no facial hair, nothing "
          "covering the eyes or mouth. ")
MASCOTS = {
    "inventor": ("A cheerful middle-aged time-travelling inventor, clean-shaven round friendly face, short messy "
                 "white hair, brass goggles pushed up and resting on top of the head above the forehead, a long teal "
                 "coat with many small pockets and brass buttons, a brass pocket watch on a chain, brown boots, a "
                 "small leather satchel across the body."),
    "apprentice": ("A curious slightly nervous young apprentice kid, round freckled face, short curly orange hair, "
                   "a red vest over a white shirt with rolled sleeves, an oversized mustard-yellow scarf, brown "
                   "shorts, tall brown boots, a small glowing blue hourglass gadget clipped to the belt."),
}
out_root = root / "_candidates"
with ComfyClient(cfg.comfy) as c:
    for name, desc in MASCOTS.items():
        out = out_root / f"mascot_{name}"
        out.mkdir(parents=True, exist_ok=True)
        for seed in (11, 22, 33, 44):
            wf = tpl.clone(); patch_flux_models(wf, cfg)
            set_image_prompt(wf, f"{COMMON}{desc} {style}")
            wf.set("PrimitiveInt", "value", 880, title_contains="Width")
            wf.set("PrimitiveInt", "value", 1168, title_contains="Height")
            wf.set("RandomNoise", "noise_seed", seed)
            wf.set_save_prefix(f"charlib/candidates/mascot_{name}_{seed}")
            run_job(c, wf, out / f"seed_{seed}.png", cfg.timeouts.image)
            print(name, seed, flush=True)

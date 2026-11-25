from __future__ import annotations

from pathlib import Path

from rich.console import Console

from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.execution import run_job
from pipeline.manifest import Manifest
from pipeline.runpaths import comfy_prefix, image_path
from pipeline.script import Scene, Script
from pipeline.stages.common import (
    patch_flux_models,
    resolve_image,
    resolve_seed,
    set_image_prompt,
    styled_image_prompt,
    wire_edit_images,
)
from pipeline.workflows import Workflow


def run(
    config: Config,
    script: Script,
    run_dir: Path,
    manifest: Manifest,
    scenes: list[Scene],
    console: Console,
    force: bool = False,
) -> None:
    image_workflow = Workflow.load(config.workflows.path(config.paths.workflows_dir, "image"), "image")
    edit_workflow = Workflow.load(config.workflows.path(config.paths.workflows_dir, "edit"), "edit")
    manifest.data.setdefault("workflows", {})["image"] = image_workflow.sha256()
    manifest.data.setdefault("workflows", {})["edit"] = edit_workflow.sha256()
    manifest.save()

    with ComfyClient(config.comfy) as client:
        for scene in scenes:
            destination = image_path(run_dir, scene)
            if not force and manifest.stage_status(scene.id, "images") == "done" and destination.exists():
                console.print(f"image {scene.id}: cached ({destination.name})")
                continue
            seed = resolve_seed(scene, script)
            mode = "edit" if scene.base_image else "text"
            if scene.base_image:
                base_path = resolve_image(config, scene.base_image)
                reference_path = resolve_image(config, scene.reference_image) if scene.reference_image else base_path
                if not base_path.is_file():
                    raise FileNotFoundError(f"scene {scene.id}: base_image not found: {base_path}")
                if not reference_path.is_file():
                    raise FileNotFoundError(f"scene {scene.id}: reference_image not found: {reference_path}")
                base_name = client.upload_image(base_path, subfolder=f"pipeline/{script.project}/refs")
                reference_name = client.upload_image(reference_path, subfolder=f"pipeline/{script.project}/refs")
                workflow = edit_workflow.clone()
                patch_flux_models(workflow, config)
                wire_edit_images(workflow, base_name, reference_name)
                workflow.set("EmptyFlux2LatentImage", "width", config.media.flux.width)
                workflow.set("EmptyFlux2LatentImage", "height", config.media.flux.height)
                workflow.set("Flux2Scheduler", "width", config.media.flux.width)
                workflow.set("Flux2Scheduler", "height", config.media.flux.height)
                prompt = (scene.edit_prompt or "").strip()
                set_image_prompt(workflow, prompt)
                detail = f"edit from {base_path.name} at {config.media.flux.width}x{config.media.flux.height}"
            else:
                workflow = image_workflow.clone()
                patch_flux_models(workflow, config)
                # dialogue backgrounds are the mascots' study: the era/setting text would add ships, togas and
                # people to it, so they only get the house style
                prompt = (scene.image_prompt or "").strip() if scene.type == "dialogue" else styled_image_prompt(scene, script)
                if config.style.house:
                    prompt = f"{prompt}, {config.style.house}"
                if scene.type == "dialogue":
                    # characters are composited on top, so the background must stay empty
                    prompt += (", eye-level view, no people, no characters, empty open floor across the "
                               "lower third of the image")
                set_image_prompt(workflow, prompt)
                workflow.set("PrimitiveInt", "value", config.media.flux.width, title_contains="Width")
                workflow.set("PrimitiveInt", "value", config.media.flux.height, title_contains="Height")
                detail = f"{config.media.flux.width}x{config.media.flux.height}"
                base_name = reference_name = None
            workflow.set("RandomNoise", "noise_seed", seed)
            workflow.set_save_prefix(comfy_prefix(script.project, "images", scene))
            console.print(f"image {scene.id}: {mode} ({detail}, seed {seed})")
            try:
                result = run_job(client, workflow, destination, config.timeouts.image)
            except Exception as exc:
                manifest.set_stage(scene.id, "images", "error", error=str(exc))
                raise
            manifest.set_stage(
                scene.id,
                "images",
                "done",
                mode=mode,
                path=str(destination.relative_to(run_dir)),
                seed=seed,
                prompt=prompt,
                base_image=base_name,
                reference_image=reference_name,
                prompt_id=result.prompt_id,
                workflow_sha=workflow.sha256(),
                elapsed=round(result.elapsed, 2),
            )
            console.print(f"image {scene.id}: {result.elapsed:.1f}s -> {destination.name}")

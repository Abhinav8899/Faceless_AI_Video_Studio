from __future__ import annotations

import secrets
from pathlib import Path

from pipeline.config import Config
from pipeline.script import Scene, Script
from pipeline.workflows import Workflow, WorkflowError


def resolve_image(config: Config, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (config.paths.refs_dir / path).resolve()


def resolve_seed(scene: Scene, script: Script) -> int:
    if scene.seed is not None:
        return scene.seed
    if script.defaults.seed is not None:
        return script.defaults.seed
    return secrets.randbelow(2**31)


def styled_image_prompt(scene: Scene, script: Script) -> str:
    base = (scene.image_prompt or "").strip()
    style = script.style.strip()
    if not (scene.use_global_style and style):
        return base
    return f"{base}, {style}" if base else style


def set_image_prompt(workflow: Workflow, prompt: str) -> None:
    primitive = workflow.find("PrimitiveStringMultiline")
    if primitive:
        for _, node in primitive:
            node["inputs"]["value"] = prompt
        return
    _, node = workflow.one("CLIPTextEncode", "Positive")
    node["inputs"]["text"] = prompt


def patch_flux_models(workflow: Workflow, config: Config) -> None:
    workflow.set("UNETLoader", "unet_name", config.models.flux_unet)
    workflow.set("CLIPLoader", "clip_name", config.models.flux_text_encoder)
    workflow.set("VAELoader", "vae_name", config.models.flux_vae)


def patch_wan_models(workflow: Workflow, config: Config) -> None:
    workflow.set("CLIPLoader", "clip_name", config.models.wan_text_encoder)
    workflow.set("VAELoader", "vae_name", config.models.wan_vae)
    for _, node in workflow.find("UnetLoaderGGUF"):
        current = str(node["inputs"].get("unet_name", ""))
        if "HighNoise" in current:
            node["inputs"]["unet_name"] = config.models.wan_gguf_high
        elif "LowNoise" in current:
            node["inputs"]["unet_name"] = config.models.wan_gguf_low
    for _, node in workflow.find("LoraLoaderModelOnly"):
        current = str(node["inputs"].get("lora_name", "")).lower()
        if "high" in current:
            node["inputs"]["lora_name"] = config.models.wan_lora_high
        elif "low" in current:
            node["inputs"]["lora_name"] = config.models.wan_lora_low


def wire_edit_images(workflow: Workflow, base_name: str, reference_name: str) -> None:
    loads = workflow.find("LoadImage")
    if not loads:
        raise WorkflowError("edit workflow has no LoadImage node")
    scales = workflow.find("ImageScaleToTotalPixels")
    base_scale = next(
        ((node_id, node) for node_id, node in scales if isinstance(node["inputs"].get("image"), list)),
        None,
    )
    if base_scale is not None:
        base_load_id = base_scale[1]["inputs"]["image"][0]
    else:
        base_load_id = loads[0][0]
    workflow.set_node(base_load_id, "image", base_name)
    reference_id: str | None = None
    for node_id, node in loads:
        title = ((node.get("_meta") or {}).get("title") or "").lower()
        if node_id != base_load_id and "reference" in title:
            reference_id = node_id
            break
    if reference_id is None:
        for node_id, _ in loads:
            if node_id != base_load_id:
                reference_id = node_id
                break
    if reference_id is None:
        reference_id = workflow.add_node(
            "pipeline_ref_image",
            "LoadImage",
            {"image": reference_name},
            "Load Image Reference",
        )
    workflow.set_node(reference_id, "image", reference_name)
    for _, node in scales:
        if not isinstance(node["inputs"].get("image"), list):
            node["inputs"]["image"] = [reference_id, 0]

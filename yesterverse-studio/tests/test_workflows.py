from pathlib import Path

from pipeline.stages.common import wire_edit_images
from pipeline.workflows import Workflow, validate_structure

API = Path(__file__).resolve().parents[1] / "workflows" / "api"


def test_all_workflows_are_valid_api_prompts() -> None:
    for name in ("tts", "image", "edit", "i2v"):
        workflow = Workflow.load(API / f"{name}.api.json", name)
        validate_structure(workflow.dump())
        assert workflow.data


def test_tts_slots() -> None:
    workflow = Workflow.load(API / "tts.api.json", "tts")
    workflow.set("UnifiedTTSTextNode", "text", "[nar|temperature:0.7] hello")
    workflow.set("UnifiedTTSTextNode", "narrator_voice", "nar.wav")
    workflow.set("Qwen3TTSEngineNode", "language", "English")
    workflow.set("SaveAudioAdvanced", "format", "flac")
    workflow.set_save_prefix("pipeline/demo/audio/scene_01")
    _, tts_text = workflow.one("UnifiedTTSTextNode")
    assert tts_text["inputs"]["text"].startswith("[nar")
    assert workflow.save_nodes()[0][1]["inputs"]["filename_prefix"].endswith("scene_01")


def test_image_slots() -> None:
    workflow = Workflow.load(API / "image.api.json", "image")
    workflow.set("PrimitiveInt", "value", 1280, title_contains="Width")
    workflow.set("PrimitiveInt", "value", 704, title_contains="Height")
    workflow.set("RandomNoise", "noise_seed", 42)
    workflow.set_save_prefix("pipeline/demo/images/scene_01")
    width = workflow.find("PrimitiveInt", "Width")[0][1]
    height = workflow.find("PrimitiveInt", "Height")[0][1]
    assert width["inputs"]["value"] == 1280
    assert height["inputs"]["value"] == 704
    assert workflow.find("RandomNoise")[0][1]["inputs"]["noise_seed"] == 42


def test_edit_workflow_wires_two_references() -> None:
    workflow = Workflow.load(API / "edit.api.json", "edit")
    wire_edit_images(workflow, "base.png", "reference.png")
    loads = workflow.find("LoadImage")
    images = {node["inputs"]["image"] for _, node in loads}
    assert {"base.png", "reference.png"} <= images
    scales = workflow.find("ImageScaleToTotalPixels")
    assert scales
    assert all(isinstance(node["inputs"].get("image"), list) for _, node in scales)


def test_i2v_slots() -> None:
    workflow = Workflow.load(API / "i2v.api.json", "i2v")
    workflow.set("LoadImage", "image", "start.png")
    workflow.set("WanImageToVideo", "width", 864)
    workflow.set("WanImageToVideo", "height", 480)
    workflow.set("WanImageToVideo", "length", 37)
    workflow.set("CLIPTextEncode", "text", "push in", title_contains="Positive")
    sampler = next(node for _, node in workflow.find("KSamplerAdvanced") if node["inputs"]["add_noise"] == "enable")
    sampler["inputs"]["noise_seed"] = 7
    assert workflow.one("WanImageToVideo")[1]["inputs"]["length"] == 37
    assert workflow.one("LoadImage")[1]["inputs"]["image"] == "start.png"
    assert sampler["inputs"]["noise_seed"] == 7

"""Several studio instances (studio, studio2, ...) share ComfyUI and the GPU but never each other's files."""
from pathlib import Path

from pipeline.config import Config, TTSConfig
from pipeline.runpaths import comfy_dir, comfy_prefix
from pipeline.script import Scene


def test_default_instance_is_unchanged():
    cfg = Config()
    tts = TTSConfig(voices=["nar", "inventor"])
    assert cfg.paths.comfy_subfolder == "pipeline"
    assert tts.file_name("nar") == "nar"
    text = "[nar|temperature:0.7] Hello. [inventor] Hi!"
    assert tts.tts_text(text) == text


def test_voice_prefix_renames_only_known_tags():
    tts = TTSConfig(voices=["nar", "nara", "host"], voice_prefix="s2_")
    assert tts.file_name("host") == "s2_host"
    text = "[nar|temperature:0.7] One. [nara] Two. [host|seed:3] Three. [pause:1s] [narrator] Four."
    assert tts.tts_text(text) == (
        "[s2_nar|temperature:0.7] One. [s2_nara] Two. [s2_host|seed:3] Three. [pause:1s] [narrator] Four."
    )


def test_comfy_subfolder_per_instance():
    cfg = Config.model_validate({"paths": {"comfy_subfolder": "studio2"}})
    scene = Scene.model_construct(id="03")
    assert comfy_dir(cfg, "demo") == "studio2/demo"
    assert comfy_prefix(cfg, "demo", "images", scene) == "studio2/demo/images/scene_03"
    assert comfy_prefix(Config(), "demo", "audio", scene) == "pipeline/demo/audio/scene_03"


def test_gpu_lock_is_shared_and_cli_follows_folder():
    from pipeline import studio
    assert studio.LOCK == Path.home() / "youtube" / ".gpu.lock"
    assert studio.STUDIO_UNIT == f"{studio.CLI}.service"
    assert studio.COMFY_UNIT == "studio-comfyui.service"

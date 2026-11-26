from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ComfyConfig(BaseModel):
    url: str = "http://127.0.0.1:8188"
    poll_interval: float = 1.0
    request_timeout: float = 30.0
    upload_timeout: float = 120.0


class PathsConfig(BaseModel):
    comfyui_root: Path = Path("/home/abhinav/ComfyUI")
    project_root: Path = Path("/home/abhinav/youtube")
    workflows_dir: Path = Path("/home/abhinav/youtube/workflows")
    runs_dir: Path = Path("/home/abhinav/youtube/runs")
    refs_dir: Path = Path("/home/abhinav/youtube/refs")
    comfy_subfolder: str = "pipeline"   # ComfyUI input/output subfolder; unique per studio instance

    @property
    def voices_dir(self) -> Path:
        return self.comfyui_root / "models" / "voices"

    @property
    def characters_dir(self) -> Path:
        return self.comfyui_root / "characters"

    @property
    def comfy_output_dir(self) -> Path:
        return self.comfyui_root / "output"

    @property
    def comfy_input_dir(self) -> Path:
        return self.comfyui_root / "input"


class WorkflowFiles(BaseModel):
    tts: str = "api/tts.api.json"
    image: str = "api/image_flux3.api.json"
    edit: str = "api/edit_flux3.api.json"
    i2v: str = "api/i2v.api.json"
    voice_design: str = "api/voice_design.api.json"   # `studio voice` (not used by renders)

    def path(self, workflows_dir: Path, name: str) -> Path:
        return (workflows_dir / getattr(self, name)).resolve()

    def all_paths(self, workflows_dir: Path) -> dict[str, Path]:
        return {name: self.path(workflows_dir, name) for name in ("tts", "image", "edit", "i2v")}


class ModelFiles(BaseModel):
    flux_unet: str = "flux3-image-klein-int8-convrot.safetensors"
    flux_text_encoder: str = "qwen3vl_4b_int8_convrot.safetensors"
    flux_vae: str = "flux2-vae.safetensors"
    wan_text_encoder: str = "umt5_xxl_fp8_e4m3fn_scaled.safetensors"
    wan_vae: str = "Wan2.1_VAE.safetensors"
    wan_lora_high: str = "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors"
    wan_lora_low: str = "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"
    wan_gguf_high: str = "Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf"
    wan_gguf_low: str = "Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf"

    def entries(self, comfyui_root: Path) -> list[tuple[str, Path]]:
        return [
            ("diffusion_models", comfyui_root / "models" / "diffusion_models" / self.flux_unet),
            ("text_encoders", comfyui_root / "models" / "text_encoders" / self.flux_text_encoder),
            ("vae", comfyui_root / "models" / "vae" / self.flux_vae),
            ("text_encoders", comfyui_root / "models" / "text_encoders" / self.wan_text_encoder),
            ("vae", comfyui_root / "models" / "vae" / self.wan_vae),
            ("loras", comfyui_root / "models" / "loras" / self.wan_lora_high),
            ("loras", comfyui_root / "models" / "loras" / self.wan_lora_low),
            ("unet", comfyui_root / "models" / "unet" / self.wan_gguf_high),
            ("unet", comfyui_root / "models" / "unet" / self.wan_gguf_low),
        ]


class FluxConfig(BaseModel):
    width: int = 1024
    height: int = 576


class WanConfig(BaseModel):
    width: int = 848
    height: int = 480
    fps: int = 16
    seconds_per_clip: float = 5.0


class RenderConfig(BaseModel):
    width: int = 1920
    height: int = 1080
    fps: int = 30
    crf: int = 18
    audio_bitrate: str = "192k"
    preset: str = "medium"


class MediaConfig(BaseModel):
    flux: FluxConfig = Field(default_factory=FluxConfig)
    wan: WanConfig = Field(default_factory=WanConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)


class TTSConfig(BaseModel):
    language: str = "English"
    narrator_voice: str = "nar.wav"
    x_vector_only_mode: bool = False
    asr_use_forced_aligner: bool = True
    output_format: str = "flac"
    voice_prefix: str = ""   # added to voice file names in ComfyUI/models/voices so studio instances never share a voice
    voices: list[str] = Field(
        default_factory=lambda: [
            "nar",
            "pip",
            "sirbumble",
            "dameironwill",
            "sirgrumbold",
            "lordvexmoor",
        ]
    )


    def file_name(self, voice: str) -> str:
        """File stem in ComfyUI/models/voices for a script voice tag (`nar` -> `s2_nar`)."""
        return f"{self.voice_prefix}{voice}"

    def tts_text(self, text: str) -> str:
        """Narration as sent to the TTS node: voice tags renamed to their prefixed files."""
        if not self.voice_prefix or not self.voices:
            return text
        names = "|".join(sorted((re.escape(v) for v in self.voices), key=len, reverse=True))
        return re.sub(rf"\[({names})(?=[\]|])", lambda m: f"[{self.voice_prefix}{m.group(1)}", text, flags=re.I)


class ComposeConfig(BaseModel):
    """Code-composed shots (still / dialogue) and overlays."""
    characters_dir: Path = PROJECT_ROOT / "assets" / "characters" / "parchment_v1"
    fonts_dir: Path = PROJECT_ROOT / "assets" / "fonts"
    camera_strength: float = 0.08      # zoom amount of still-shot camera moves
    finish_strength: float = 0.35      # paper vignette/grain over every composed shot (0 = off)
    ground: float = 0.965              # feet line for characters, fraction of frame height


class StyleConfig(BaseModel):
    """House style added to every generated image prompt, and the default Wan negative prompt."""
    house: str = ""
    negative: str = ""


class SubjectsConfig(BaseModel):
    """Consistent subjects: reference portraits + the automatic likeness check (pipeline/likeness.py)."""
    portrait_candidates: int = 3        # portraits drawn per subject; the clearest single subject is kept
    portrait_size: int = 1024           # square portrait, pixels
    compose_from_text: bool = True      # draw the scene from text first, then redraw it from the portraits
    denoise: float = 0.8                # how much the portrait pass may change the text-drawn layout (0-1)
    check: bool = True                  # compare every subject scene with its portrait, redraw when it does not match
    threshold_person: float = 0.72      # head similarity (0-1) a person must reach
    threshold_thing: float = 0.65       # whole-subject similarity for animals, objects, machines, vehicles...
    max_attempts: int = 3               # drawings per scene before the best one is kept and flagged
    min_area: float = 0.012             # subjects smaller than this fraction of the picture are not checked
    python: Path = Path("/home/abhinav/ComfyUI/venv/bin/python")   # has torch + transformers
    device: str = "cpu"                 # cpu leaves the GPU to ComfyUI
    detector: str = "google/owlv2-base-patch16-ensemble"
    embedder: str = "facebook/dinov2-base"


class DiskConfig(BaseModel):
    min_free_gb: float = 10.0


class TimeoutConfig(BaseModel):
    tts: float = 1800.0
    image: float = 900.0
    video: float = 3600.0


class Config(BaseModel):
    comfy: ComfyConfig = Field(default_factory=ComfyConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    workflows: WorkflowFiles = Field(default_factory=WorkflowFiles)
    models: ModelFiles = Field(default_factory=ModelFiles)
    media: MediaConfig = Field(default_factory=MediaConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    compose: ComposeConfig = Field(default_factory=ComposeConfig)
    style: StyleConfig = Field(default_factory=StyleConfig)
    subjects: SubjectsConfig = Field(default_factory=SubjectsConfig)
    disk: DiskConfig = Field(default_factory=DiskConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)


def load_config(path: str | Path | None = None) -> Config:
    candidate = path or os.environ.get("PIPELINE_CONFIG") or PROJECT_ROOT / "config.yaml"
    config_path = Path(candidate)
    if not config_path.exists():
        return Config()
    data = yaml.safe_load(config_path.read_text()) or {}
    return Config.model_validate(data)

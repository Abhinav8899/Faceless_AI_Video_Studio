from __future__ import annotations

import os
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
    # "~" is expanded and relative paths are resolved against the repo folder (see load_config)
    comfyui_root: Path = Path("~/ComfyUI")
    project_root: Path = Path(".")
    workflows_dir: Path = Path("workflows")
    runs_dir: Path = Path("output")                  # one folder per video: deliverables + work/ logs/ scripts/
    refs_dir: Path = Path("refs")

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
    image: str = "api/image.api.json"
    edit: str = "api/edit.api.json"
    i2v: str = "api/i2v.api.json"
    voice_design: str = "api/voice_design.api.json"   # `studio voice` (not used by renders)

    def path(self, workflows_dir: Path, name: str) -> Path:
        return (workflows_dir / getattr(self, name)).resolve()

    def all_paths(self, workflows_dir: Path) -> dict[str, Path]:
        return {name: self.path(workflows_dir, name) for name in ("tts", "image", "edit", "i2v")}


class ModelFiles(BaseModel):
    flux_unet: str = "flux-2-klein-4b.safetensors"
    flux_text_encoder: str = "qwen_3_4b.safetensors"
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
    voices: list[str] = Field(
        default_factory=lambda: ["nar", "inventor", "apprentice"]
    )


class ComposeConfig(BaseModel):
    """Code-composed shots (still / dialogue) and overlays."""
    characters_dir: Path = PROJECT_ROOT / "assets" / "characters" / "library"
    fonts_dir: Path = PROJECT_ROOT / "assets" / "fonts"
    camera_strength: float = 0.08      # zoom amount of still-shot camera moves
    finish_strength: float = 0.35      # paper vignette/grain over every composed shot (0 = off)
    ground: float = 0.965              # feet line for characters, fraction of frame height


class StyleConfig(BaseModel):
    """House style added to every generated image prompt, and the default Wan negative prompt."""
    house: str = ""
    negative: str = ""


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
    disk: DiskConfig = Field(default_factory=DiskConfig)
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)


def _resolve(p: Path) -> Path:
    p = Path(os.path.expanduser(str(p)))
    return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()


def _resolve_paths(config: Config) -> Config:
    for name in ("comfyui_root", "project_root", "workflows_dir", "runs_dir", "refs_dir"):
        setattr(config.paths, name, _resolve(getattr(config.paths, name)))
    config.compose.characters_dir = _resolve(config.compose.characters_dir)
    config.compose.fonts_dir = _resolve(config.compose.fonts_dir)
    return config


def load_config(path: str | Path | None = None) -> Config:
    candidate = path or os.environ.get("PIPELINE_CONFIG") or PROJECT_ROOT / "config.yaml"
    config_path = Path(candidate)
    if not config_path.exists():
        return _resolve_paths(Config())
    data = yaml.safe_load(config_path.read_text()) or {}
    return _resolve_paths(Config.model_validate(data))

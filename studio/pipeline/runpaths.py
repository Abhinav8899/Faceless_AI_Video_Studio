from __future__ import annotations

from pathlib import Path

from pipeline.config import Config
from pipeline.script import Scene, Script


def project_dir(config: Config, project: str) -> Path:
    """Everything about one video: deliverables at the top, work/, logs/, scripts/."""
    return config.paths.runs_dir / project


def work_dir(config: Config, project: str) -> Path:
    return project_dir(config, project) / "work"


def run_dir(config: Config, script: Script) -> Path:
    return work_dir(config, script.project)


def manifest_path(directory: Path) -> Path:
    return directory / "manifest.json"


def script_path(directory: Path) -> Path:
    return directory / "script.json"


def audio_path(directory: Path, scene: Scene) -> Path:
    return directory / "audio" / f"scene_{scene.id}.flac"


def image_path(directory: Path, scene: Scene) -> Path:
    return directory / "images" / f"scene_{scene.id}.png"


def clip_dir(directory: Path, scene: Scene) -> Path:
    return directory / "video" / f"scene_{scene.id}"


def clip_path(directory: Path, scene: Scene, index: int) -> Path:
    return clip_dir(directory, scene) / f"clip_{index:02d}.mp4"


def last_frame_path(directory: Path, scene: Scene, index: int) -> Path:
    return clip_dir(directory, scene) / f"last_{index:02d}.png"


def scene_video_path(directory: Path, scene: Scene) -> Path:
    return directory / "scenes" / f"scene_{scene.id}.mp4"


def composed_path(directory: Path, scene: Scene) -> Path:
    return directory / "composed" / f"scene_{scene.id}.mp4"


def render_dir(directory: Path) -> Path:
    return directory / "render"


def render_video_path(directory: Path, scene: Scene) -> Path:
    return render_dir(directory) / f"scene_{scene.id}.mp4"


def render_audio_path(directory: Path, scene: Scene) -> Path:
    return render_dir(directory) / f"scene_{scene.id}.flac"


def full_audio_path(directory: Path) -> Path:
    return directory / "audio" / "full.flac"


def final_path(directory: Path) -> Path:
    return directory / "final.mp4"


def comfy_dir(config: Config, project: str) -> str:
    """ComfyUI input/output subfolder for one project of this studio instance."""
    return f"{config.paths.comfy_subfolder}/{project}"


def comfy_prefix(config: Config, project: str, stage: str, scene: Scene) -> str:
    return f"{comfy_dir(config, project)}/{stage}/scene_{scene.id}"

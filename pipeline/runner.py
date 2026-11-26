from __future__ import annotations

import json
import shutil
from pathlib import Path

from rich.console import Console
from rich.table import Table

from pipeline.config import Config
from pipeline.manifest import Manifest
from pipeline.runpaths import (
    clip_dir,
    composed_path,
    final_path,
    image_path,
    manifest_path,
    render_audio_path,
    render_video_path,
    run_dir,
    scene_video_path,
    script_path,
)
from pipeline.script import Scene, Script
from pipeline.stages import audio as audio_stage
from pipeline.stages import compose as compose_stage
from pipeline.stages import images as images_stage
from pipeline.stages import render as render_stage
from pipeline.stages import video as video_stage

STAGES = ("audio", "images", "video", "compose", "render")

STAGE_WORKFLOWS = {
    "audio": ("tts",),
    "images": ("image", "edit"),
    "video": ("i2v",),
    "compose": (),
    "render": (),
}


def select_scenes(script: Script, only_scenes: list[str] | None) -> list[Scene]:
    if not only_scenes:
        return list(script.scenes)
    by_id = {scene.id: scene for scene in script.scenes}
    missing = [scene_id for scene_id in only_scenes if scene_id not in by_id]
    if missing:
        raise ValueError(f"unknown scene id(s): {', '.join(missing)}")
    return [by_id[scene_id] for scene_id in only_scenes]


def prepare_run(config: Config, script: Script) -> tuple[Path, Manifest]:
    directory = run_dir(config, script)
    directory.mkdir(parents=True, exist_ok=True)
    script_path(directory).write_text(script.model_dump_json(indent=2))
    manifest = Manifest.load_or_create(manifest_path(directory), script.project)
    manifest.data["config"] = config.model_dump(mode="json")
    manifest.data["project"] = script.project
    manifest.save()
    return directory, manifest


def check_workflows(config: Config, stages: tuple[str, ...]) -> None:
    required: set[str] = set()
    for stage in stages:
        required.update(STAGE_WORKFLOWS.get(stage, ()))
    paths = config.workflows.all_paths(config.paths.workflows_dir)
    missing = [f"{name}.api.json" for name in sorted(required) if not paths[name].is_file()]
    if missing:
        raise FileNotFoundError(
            "missing API workflows in "
            f"{config.paths.workflows_dir}: {', '.join(missing)}"
        )


def run(
    config: Config,
    script: Script,
    stage: str = "all",
    only_scenes: list[str] | None = None,
    force: bool = False,
    console: Console | None = None,
) -> Path:
    console = console or Console()
    stages: tuple[str, ...] = STAGES if stage == "all" else (stage,)
    check_workflows(config, stages)
    script.validate_against(config.tts.voices)
    directory, manifest = prepare_run(config, script)
    scenes = select_scenes(script, only_scenes)
    console.print(
        f"project [bold]{script.project}[/bold]: {len(scenes)} scene(s), "
        f"stages {', '.join(stages)}, run dir {directory}"
    )
    for name in stages:
        console.rule(name)
        if name == "audio":
            audio_stage.run(config, script, directory, manifest, scenes, console, force)
        elif name == "images":
            images_stage.run(config, script, directory, manifest, scenes, console, force)
        elif name == "video":
            video_stage.run(config, script, directory, manifest, scenes, console, force)
        elif name == "compose":
            compose_stage.run(config, script, directory, manifest, scenes, console, force)
        elif name == "render":
            render_stage.run(config, script, directory, manifest, scenes, console, force)
    final = final_path(directory)
    return final if final.is_file() else directory


def plan(
    config: Config,
    script: Script,
    only_scenes: list[str] | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()
    directory = run_dir(config, script)
    manifest_data: dict = {}
    manifest_file = manifest_path(directory)
    if manifest_file.is_file():
        manifest_data = json.loads(manifest_file.read_text())
    scenes = select_scenes(script, only_scenes)
    table = Table(title=f"plan: {script.project}")
    for column in ("scene", "type", "mode", "narration", "audio", "image", "video", "compose"):
        table.add_column(column)
    for scene in scenes:
        scene_manifest = (manifest_data.get("scenes") or {}).get(scene.id, {}).get("stages", {})
        mode = "subjects" if scene.subjects else "edit" if scene.base_image else "text"
        table.add_row(
            scene.id,
            scene.type,
            mode,
            f"{len(scene.narration)} chars",
            scene_manifest.get("audio", {}).get("status", "-"),
            scene_manifest.get("images", {}).get("status", "-"),
            scene_manifest.get("video", {}).get("status", "-") if scene.type == "wan" else "n/a",
            scene_manifest.get("compose", {}).get("status", "-"),
        )
    console.print(table)
    console.print(
        f"flux {config.media.flux.width}x{config.media.flux.height}, "
        f"wan {config.media.wan.width}x{config.media.wan.height}@{config.media.wan.fps}, "
        f"render {config.media.render.width}x{config.media.render.height}@{config.media.render.fps}"
    )
    paths = config.workflows.all_paths(config.paths.workflows_dir)
    for name, path in paths.items():
        console.print(f"workflow {name}: {'ok' if path.is_file() else 'missing'} ({path})")


def clean(
    config: Config,
    script: Script,
    only_scenes: list[str] | None = None,
    console: Console | None = None,
) -> None:
    console = console or Console()
    directory = run_dir(config, script)
    if not directory.is_dir():
        console.print(f"clean: nothing at {directory}")
        return
    selected = select_scenes(script, only_scenes) if only_scenes else None
    removed = 0
    if selected is None:
        for name in ("images", "video", "scenes", "composed", "render"):
            target = directory / name
            if target.is_dir():
                removed += sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
                shutil.rmtree(target)
    else:
        for scene in selected:
            for path in (image_path(directory, scene), scene_video_path(directory, scene), composed_path(directory, scene),
                         render_video_path(directory, scene), render_audio_path(directory, scene)):
                if path.is_file():
                    removed += path.stat().st_size
                    path.unlink()
            directory_to_remove = clip_dir(directory, scene)
            if directory_to_remove.is_dir():
                removed += sum(path.stat().st_size for path in directory_to_remove.rglob("*") if path.is_file())
                shutil.rmtree(directory_to_remove)
        for name in ("images", "video", "scenes", "composed", "render"):
            target = directory / name
            if target.is_dir() and not any(target.iterdir()):
                target.rmdir()
    audio_dir = directory / "audio"
    if audio_dir.is_dir():
        allowed = {f"scene_{scene.id}.flac" for scene in selected} if selected else None
        for path in audio_dir.glob("scene_*.flac"):
            if allowed is None or path.name in allowed:
                removed += path.stat().st_size
                path.unlink()
    console.print(f"clean: removed {removed / 1_000_000:.1f} MB from {directory}")

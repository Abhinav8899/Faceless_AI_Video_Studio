from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from pipeline.compose import CharacterPlan, Library, OverlayPlan, ShotPlan, render
from pipeline.config import Config
from pipeline.ffmpeg import ffprobe_duration
from pipeline.manifest import Manifest
from pipeline.runpaths import audio_path, composed_path, image_path, scene_video_path
from pipeline.script import Scene, Script
from pipeline.timing import scene_tail


def needs_compose(scene: Scene) -> bool:
    """still/dialogue are always composed; wan scenes only when they carry overlays."""
    return scene.type in ("still", "dialogue", "map") or bool(scene.overlays)


def build_plan(config: Config, script: Script, run_dir: Path, scene: Scene) -> ShotPlan:
    cfg = config.compose
    render_cfg = config.media.render
    audio = audio_path(run_dir, scene)
    if not audio.is_file():
        raise FileNotFoundError(f"scene {scene.id}: audio missing, run the audio stage first ({audio})")
    duration = ffprobe_duration(audio) + scene_tail(scene.tail_silence, script.defaults.tail_silence,
                                                    script.defaults.scene_gap)
    for ov in scene.overlays:                    # the like & subscribe badge always gets its full 5 seconds
        if ov.kind == "subscribe":
            duration = max(duration, ov.start + 5.2)
    plan = ShotPlan(
        duration=duration,
        width=render_cfg.width,
        height=render_cfg.height,
        fps=render_cfg.fps,
        audio=audio,
        camera_strength=cfg.camera_strength,
        finish_strength=cfg.finish_strength,
        ground=cfg.ground,
        fonts_dir=cfg.fonts_dir,
    )
    if scene.type == "wan":
        video = scene_video_path(run_dir, scene)
        if not video.is_file():
            raise FileNotFoundError(f"scene {scene.id}: video missing, run the video stage first ({video})")
        plan.background_video = video
        plan.camera = "static"
    elif scene.type == "map":
        plan.map_spec = scene.map.model_dump()   # the map draws its own camera (wide -> story area)
        plan.camera = "static"
    else:
        image = image_path(run_dir, scene)
        if not image.is_file():
            raise FileNotFoundError(f"scene {scene.id}: image missing, run the images stage first ({image})")
        plan.background = image
        plan.camera = scene.camera or "push_in"
        if scene.type == "dialogue":
            plan.camera_strength = cfg.camera_strength * 0.45     # dialogue: a gentle drift, not a zoom
    speaker = scene.speaker()
    for c in scene.characters:
        plan.characters.append(CharacterPlan(
            name=c.name,
            pose=c.pose,
            side=c.side,
            expression=c.expression,
            beats=[(b.t, b.expression) for b in c.beats],
            speaking=(speaker == c.name),
            height_frac=c.height,
            flip=c.flip,
        ))
    for ov in scene.overlays:
        default_end = ov.start + 5.0 if ov.kind == "subscribe" else duration - 0.25
        end = ov.end if ov.end is not None else max(ov.start + 0.5, default_end)
        position = ov.position if "position" in ov.model_fields_set else \
            {"stat": "center", "headline": "center"}.get(ov.kind, ov.position)
        plan.overlays.append(OverlayPlan(ov.kind, ov.text, ov.start, min(end, duration), position, label=ov.label))
    return plan


def run(
    config: Config,
    script: Script,
    run_dir: Path,
    manifest: Manifest,
    scenes: list[Scene],
    console: Console,
    force: bool = False,
) -> None:
    library = None
    if any(scene.characters for scene in scenes):
        library = Library(config.compose.characters_dir)
        script.validate_characters(library)
    for scene in scenes:
        destination = composed_path(run_dir, scene)
        if not needs_compose(scene):
            console.print(f"compose {scene.id}: {scene.type} scene without overlays, nothing to compose")
            continue
        inputs = [p for p in (audio_path(run_dir, scene), image_path(run_dir, scene), scene_video_path(run_dir, scene))
                  if p.is_file()]
        fresh = destination.exists() and all(destination.stat().st_mtime >= p.stat().st_mtime for p in inputs)
        if not force and manifest.stage_status(scene.id, "compose") == "done" and fresh:
            console.print(f"compose {scene.id}: cached ({destination.name})")
            continue
        plan = build_plan(config, script, run_dir, scene)
        who = ", ".join(f"{c.name}{'*' if c.speaking else ''}" for c in plan.characters)
        console.print(
            f"compose {scene.id}: {scene.type}, {plan.duration:.2f}s, camera {plan.camera}"
            + (f", characters {who}" if who else "")
            + (f", {len(plan.overlays)} overlay(s)" if plan.overlays else "")
        )
        start = time.monotonic()
        try:
            render(plan, library, destination, crf=config.media.render.crf, preset=config.media.render.preset)
        except Exception as exc:
            manifest.set_stage(scene.id, "compose", "error", error=str(exc))
            raise
        elapsed = time.monotonic() - start
        manifest.set_stage(
            scene.id, "compose", "done",
            path=str(destination.relative_to(run_dir)),
            duration=round(plan.duration, 3),
            type=scene.type,
            elapsed=round(elapsed, 2),
        )
        # a re-composed shot makes the final cut stale
        manifest.data.pop("render", None)
        manifest.save()
        console.print(f"compose {scene.id}: {elapsed:.1f}s -> {destination.name}")

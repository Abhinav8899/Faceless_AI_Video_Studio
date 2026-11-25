from __future__ import annotations

from pathlib import Path

from rich.console import Console

from pipeline.config import Config
from pipeline.ffmpeg import (
    audio_segment,
    concat_audio,
    concat_videos,
    ffprobe_duration,
    mux_final,
    normalize_scene,
)
from pipeline.manifest import Manifest
from pipeline.runpaths import (
    audio_path,
    composed_path,
    final_path,
    full_audio_path,
    render_audio_path,
    render_dir,
    render_video_path,
    scene_video_path,
)
from pipeline.script import Scene, Script
from pipeline.timing import render_duration


def run(
    config: Config,
    script: Script,
    run_dir: Path,
    manifest: Manifest,
    scenes: list[Scene],
    console: Console,
    force: bool = False,
) -> None:
    output = final_path(run_dir)
    sources = []
    for scene in scenes:
        for path in (composed_path(run_dir, scene), scene_video_path(run_dir, scene), audio_path(run_dir, scene)):
            if path.is_file():
                sources.append(path)
    fresh = output.exists() and all(output.stat().st_mtime >= path.stat().st_mtime for path in sources)
    if not force and manifest.data.get("render", {}).get("status") == "done" and fresh:
        console.print(f"render: cached ({output.name})")
        return
    render_root = render_dir(run_dir)
    render_root.mkdir(parents=True, exist_ok=True)
    video_parts: list[Path] = []
    audio_parts: list[Path] = []
    scene_durations: dict[str, float] = {}
    for scene in scenes:
        composed = composed_path(run_dir, scene)
        source_video = composed if composed.is_file() else scene_video_path(run_dir, scene)
        source_audio = audio_path(run_dir, scene)
        if not source_video.is_file():
            stage = "video" if scene.type == "wan" else "compose"
            raise FileNotFoundError(f"scene {scene.id}: video missing, run the {stage} stage first ({source_video})")
        if not source_audio.is_file():
            raise FileNotFoundError(f"scene {scene.id}: audio missing, run the audio stage first ({source_audio})")
        duration = render_duration(ffprobe_duration(source_video), config.media.render.fps)
        video_part = normalize_scene(
            source_video,
            render_video_path(run_dir, scene),
            width=config.media.render.width,
            height=config.media.render.height,
            fps=config.media.render.fps,
            duration=duration,
            crf=config.media.render.crf,
            preset=config.media.render.preset,
        )
        audio_part = audio_segment(source_audio, render_audio_path(run_dir, scene), duration)
        video_parts.append(video_part)
        audio_parts.append(audio_part)
        scene_durations[scene.id] = duration
        console.print(f"render {scene.id}: {duration:.3f}s aligned to {config.media.render.fps} fps")

    video_only = render_root / "video.mp4"
    concat_videos(video_parts, video_only, render_root / "videos.txt")
    full_audio = concat_audio(audio_parts, full_audio_path(run_dir), render_root / "audios.txt")
    mux_final(video_only, full_audio, output, audio_bitrate=config.media.render.audio_bitrate)
    duration = ffprobe_duration(output)
    manifest.data["render"] = {
        "status": "done",
        "path": str(output.relative_to(run_dir)),
        "duration": duration,
        "width": config.media.render.width,
        "height": config.media.render.height,
        "fps": config.media.render.fps,
        "scenes": scene_durations,
    }
    manifest.save()
    for scene in scenes:
        manifest.set_stage(scene.id, "render", "done", duration=scene_durations[scene.id])
    console.print(f"render: {duration:.2f}s -> {output}")

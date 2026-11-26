from __future__ import annotations

from pathlib import Path

from rich.console import Console

from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.execution import run_job
from pipeline.ffmpeg import concat_clips, extract_last_frame, ffprobe_duration
from pipeline.manifest import Manifest
from pipeline.runpaths import (
    audio_path,
    clip_dir,
    clip_path,
    comfy_dir,
    comfy_prefix,
    image_path,
    last_frame_path,
    scene_video_path,
)
from pipeline.script import Scene, Script
from pipeline.stages.common import patch_wan_models, resolve_seed
from pipeline.timing import clip_seed, plan_clips, scene_tail
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
    template = Workflow.load(config.workflows.path(config.paths.workflows_dir, "i2v"), "i2v")
    manifest.data.setdefault("workflows", {})["i2v"] = template.sha256()
    manifest.save()
    fps = config.media.wan.fps

    with ComfyClient(config.comfy) as client:
        for scene in scenes:
            if scene.type != "wan":
                console.print(f"video {scene.id}: {scene.type} scene, composed in code (no Wan)")
                continue
            scene_audio = audio_path(run_dir, scene)
            scene_image = image_path(run_dir, scene)
            if not scene_audio.is_file():
                raise FileNotFoundError(f"scene {scene.id}: audio missing, run the audio stage first ({scene_audio})")
            if not scene_image.is_file():
                raise FileNotFoundError(f"scene {scene.id}: image missing, run the images stage first ({scene_image})")
            destination = scene_video_path(run_dir, scene)
            newest_input = max(scene_image.stat().st_mtime, scene_audio.stat().st_mtime)
            if destination.exists() and destination.stat().st_mtime < newest_input:
                # picture or narration changed since this scene was animated: drop the old clips
                import shutil
                shutil.rmtree(clip_dir(run_dir, scene), ignore_errors=True)
                destination.unlink()
                manifest.scene(scene.id).get("stages", {}).pop("video", None)
                manifest.save()
                console.print(f"video {scene.id}: start image or audio changed, re-animating")
            if not force and manifest.stage_status(scene.id, "video") == "done" and destination.exists():
                console.print(f"video {scene.id}: cached ({destination.name})")
                continue
            entry = manifest.scene(scene.id).get("stages", {}).get("video", {})
            base_seed = entry.get("base_seed")
            if not isinstance(base_seed, int):
                base_seed = resolve_seed(scene, script)
            tail = scene_tail(scene.tail_silence, script.defaults.tail_silence, script.defaults.scene_gap)
            target = ffprobe_duration(scene_audio) + tail
            frame_plan = plan_clips(target, fps, config.media.wan.seconds_per_clip)
            manifest.set_stage(scene.id, "video", "running", base_seed=base_seed, target_seconds=target, frames=frame_plan)
            image_name = client.upload_image(scene_image, subfolder=f"{comfy_dir(config, script.project)}/frames")
            clips: list[Path] = []
            clip_dir(run_dir, scene).mkdir(parents=True, exist_ok=True)
            console.print(
                f"video {scene.id}: target {target:.2f}s in {len(frame_plan)} clip(s) {frame_plan} "
                f"at {config.media.wan.width}x{config.media.wan.height}@{fps}"
            )
            for index, frames in enumerate(frame_plan, start=1):
                clip_file = clip_path(run_dir, scene, index)
                if index == 1:
                    start_source = scene_image
                    start_name = image_name
                else:
                    start_source = last_frame_path(run_dir, scene, index - 1)
                    start_name = client.upload_image(
                        start_source, subfolder=f"{comfy_dir(config, script.project)}/frames"
                    )
                if not force and clip_file.is_file():
                    console.print(f"  clip {index}/{len(frame_plan)}: cached")
                else:
                    workflow = template.clone()
                    patch_wan_models(workflow, config)
                    workflow.set("LoadImage", "image", start_name)
                    workflow.set("WanImageToVideo", "width", config.media.wan.width)
                    workflow.set("WanImageToVideo", "height", config.media.wan.height)
                    workflow.set("WanImageToVideo", "length", frames)
                    workflow.set("WanImageToVideo", "batch_size", 1)
                    workflow.set("CLIPTextEncode", "text", scene.motion_prompt or "", title_contains="Positive")
                    negative = ", ".join(n for n in (script.negative.strip(), config.style.negative.strip()) if n)
                    if negative:
                        workflow.set("CLIPTextEncode", "text", negative, title_contains="Negative")
                    workflow.set("PrimitiveFloat", "value", fps, title_contains="FPS")
                    sampler = next(
                        (
                            node
                            for _, node in workflow.find("KSamplerAdvanced")
                            if node["inputs"].get("add_noise") == "enable"
                        ),
                        None,
                    )
                    if sampler is None:
                        raise RuntimeError("i2v workflow has no KSamplerAdvanced(add_noise=enable)")
                    sampler["inputs"]["noise_seed"] = clip_seed(base_seed, index - 1)
                    workflow.set_save_prefix(comfy_prefix(config, script.project, "video", scene))
                    console.print(
                        f"  clip {index}/{len(frame_plan)}: {frames} frames "
                        f"({frames / fps:.2f}s), seed {clip_seed(base_seed, index - 1)}"
                    )
                    try:
                        result = run_job(client, workflow, clip_file, config.timeouts.video)
                    except Exception as exc:
                        manifest.set_stage(scene.id, "video", "error", error=str(exc))
                        raise
                    console.print(f"  clip {index}/{len(frame_plan)}: {result.elapsed:.1f}s")
                clips.append(clip_file)
                if index < len(frame_plan):
                    extract_last_frame(clip_file, last_frame_path(run_dir, scene, index))
            concat_clips(
                clips,
                destination,
                duration=target,
                fps=fps,
                list_path=clip_dir(run_dir, scene) / "clips.txt",
                crf=config.media.render.crf,
                preset=config.media.render.preset,
            )
            duration = ffprobe_duration(destination)
            manifest.set_stage(
                scene.id,
                "video",
                "done",
                path=str(destination.relative_to(run_dir)),
                duration=duration,
                target_seconds=target,
                frames=frame_plan,
                clips=len(clips),
                base_seed=base_seed,
            )
            console.print(f"video {scene.id}: {duration:.2f}s -> {destination.name}")

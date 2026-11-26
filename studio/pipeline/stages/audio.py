from __future__ import annotations

from pathlib import Path

from rich.console import Console

from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.execution import run_job
from pipeline.ffmpeg import ffprobe_duration
from pipeline.manifest import Manifest
from pipeline.runpaths import audio_path, comfy_prefix
from pipeline.script import Scene, Script
from pipeline.stages.common import resolve_seed
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
    workflow_path = config.workflows.path(config.paths.workflows_dir, "tts")
    template = Workflow.load(workflow_path, "tts")
    manifest.data.setdefault("workflows", {})["tts"] = template.sha256()
    manifest.save()

    with ComfyClient(config.comfy) as client:
        for scene in scenes:
            destination = audio_path(run_dir, scene)
            if not force and manifest.stage_status(scene.id, "audio") == "done" and destination.exists():
                console.print(f"audio {scene.id}: cached ({destination.name})")
                continue
            seed = resolve_seed(scene, script)
            workflow = template.clone()
            workflow.set("UnifiedTTSTextNode", "text", config.tts.tts_text(scene.narration))
            workflow.set("UnifiedTTSTextNode", "narrator_voice", config.tts.voice_prefix + config.tts.narrator_voice)
            workflow.set("UnifiedTTSTextNode", "seed", seed)
            workflow.set("Qwen3TTSEngineNode", "language", config.tts.language)
            workflow.set("Qwen3TTSEngineNode", "x_vector_only_mode", config.tts.x_vector_only_mode)
            workflow.set("Qwen3TTSEngineNode", "asr_use_forced_aligner", config.tts.asr_use_forced_aligner)
            workflow.set("SaveAudioAdvanced", "format", config.tts.output_format)
            workflow.set_save_prefix(comfy_prefix(config, script.project, "audio", scene))
            console.print(f"audio {scene.id}: generating speech with {len(script.voice_names())} voice tag(s)")
            try:
                result = run_job(client, workflow, destination, config.timeouts.tts)
            except Exception as exc:
                manifest.set_stage(scene.id, "audio", "error", error=str(exc))
                raise
            duration = ffprobe_duration(destination)
            manifest.set_stage(
                scene.id,
                "audio",
                "done",
                path=str(destination.relative_to(run_dir)),
                duration=duration,
                seed=seed,
                prompt_id=result.prompt_id,
                workflow_sha=workflow.sha256(),
                elapsed=round(result.elapsed, 2),
            )
            console.print(f"audio {scene.id}: {duration:.2f}s in {result.elapsed:.1f}s -> {destination.name}")

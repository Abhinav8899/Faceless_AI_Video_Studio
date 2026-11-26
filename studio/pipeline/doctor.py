from __future__ import annotations

import platform
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx
from rich.console import Console
from rich.table import Table

from pipeline import __version__
from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.ffmpeg import ffmpeg_version
from pipeline.workflows import Workflow, WorkflowError

OK = "ok"
WARN = "warn"
FAIL = "fail"

STATUS_STYLE = {OK: "green", WARN: "yellow", FAIL: "red"}


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


def check_python() -> Check:
    version = platform.python_version()
    in_venv = sys.prefix != sys.base_prefix
    uv = shutil.which("uv")
    parts = [f"Python {version}", "venv=yes" if in_venv else "venv=no"]
    parts.append(f"uv={uv}" if uv else "uv=missing (venv fallback)")
    status = OK if sys.version_info >= (3, 10) else FAIL
    return Check("runtime", status, ", ".join(parts))


def check_tools() -> Check:
    ffmpeg = ffmpeg_version()
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg:
        return Check("ffmpeg", FAIL, "ffmpeg not found on PATH")
    if not ffprobe:
        return Check("ffmpeg", WARN, f"{ffmpeg.split()[2]}, ffprobe not found")
    return Check("ffmpeg", OK, f"{ffmpeg.split()[2]}, ffprobe present")


def check_layout(config: Config) -> Check:
    paths = config.paths
    required = {
        "comfyui_root": paths.comfyui_root,
        "comfy_output": paths.comfy_output_dir,
    }
    optional = {
        "workflows": paths.workflows_dir,
        "refs": paths.refs_dir,
        "runs": paths.runs_dir,
    }
    missing_required = [name for name, path in required.items() if not path.is_dir()]
    missing_optional = [name for name, path in optional.items() if not path.is_dir()]
    if missing_required:
        return Check("layout", FAIL, f"missing: {', '.join(missing_required)}")
    if missing_optional:
        return Check("layout", WARN, f"missing dirs: {', '.join(missing_optional)}")
    return Check("layout", OK, f"project={paths.project_root}, comfy={paths.comfyui_root}")


def check_disk(config: Config) -> Check:
    anchor = config.paths.runs_dir
    if not anchor.exists():
        anchor = config.paths.project_root if config.paths.project_root.exists() else Path("/")
    usage = shutil.disk_usage(anchor)
    free_gb = usage.free / 1_000_000_000
    detail = f"{free_gb:.1f} GB free at {anchor} (min {config.disk.min_free_gb:.0f} GB)"
    if free_gb < 1.0:
        return Check("disk", FAIL, detail)
    if free_gb < config.disk.min_free_gb:
        return Check("disk", WARN, detail)
    return Check("disk", OK, detail)


def check_models(config: Config) -> Check:
    entries = config.models.entries(config.paths.comfyui_root)
    missing = [f"{label}/{path.name}" for label, path in entries if not path.is_file() or path.stat().st_size == 0]
    if missing:
        return Check("models", FAIL, "missing: " + ", ".join(missing))
    return Check("models", OK, f"{len(entries)} checkpoint/LoRA/GGUF files present")


def check_voices(config: Config) -> Check:
    voices_dir = config.paths.voices_dir
    missing: list[str] = []
    missing_transcripts: list[str] = []
    for voice in config.tts.voices:
        wav = voices_dir / f"{config.tts.file_name(voice)}.wav"
        if not wav.is_file():
            missing.append(wav.name)
            continue
        reference = voices_dir / f"{config.tts.file_name(voice)}.reference.txt"
        plain = voices_dir / f"{config.tts.file_name(voice)}.txt"
        if not reference.is_file() and not plain.is_file():
            missing_transcripts.append(voice)
    if missing:
        return Check("voices", FAIL, f"missing: {', '.join(missing)} in {voices_dir}")
    if missing_transcripts:
        return Check("voices", WARN, f"{len(config.tts.voices)} voices, no transcript for: {', '.join(missing_transcripts)}")
    return Check(
        "voices",
        OK,
        f"{len(config.tts.voices)} voices with reference transcripts, narrator={config.tts.narrator_voice}",
    )


def check_compose(config: Config) -> Check:
    try:
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        return Check("compose", FAIL, f"missing python package: {exc.name} (pip install pillow numpy)")
    index = config.compose.characters_dir / "index.json"
    fonts = sorted(p.name for p in config.compose.fonts_dir.glob("*")) if config.compose.fonts_dir.is_dir() else []
    if not index.is_file():
        return Check("compose", WARN, f"no character library index at {index} (dialogue scenes unavailable)")
    from pipeline.compose import Library
    lib = Library(config.compose.characters_dir)
    detail = f"characters: {', '.join(lib.characters())}; fonts: {', '.join(fonts) or 'none (DejaVu fallback)'}"
    return Check("compose", OK if fonts else WARN, detail)


def check_workflows(config: Config) -> Check:
    files = config.workflows.all_paths(config.paths.workflows_dir)
    missing = [name for name, path in files.items() if not path.is_file()]
    if missing:
        return Check("workflow api", WARN, "pending exports: " + ", ".join(f"{name}.api.json" for name in missing))
    try:
        counts = {name: len(Workflow.load(path, name).data) for name, path in files.items()}
    except (OSError, ValueError, WorkflowError) as exc:
        return Check("workflow api", FAIL, f"invalid API workflow: {exc}")
    summary = ", ".join(f"{name}={count}" for name, count in counts.items())
    return Check("workflow api", OK, f"nodes: {summary}")


def check_comfy(config: Config) -> list[Check]:
    try:
        with ComfyClient(config.comfy) as client:
            stats = client.system_stats()
            queue = client.queue()
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        return [Check("comfyui", FAIL, f"{config.comfy.url}: {exc}")]
    system = stats.get("system", {})
    devices = stats.get("devices", []) or []
    version = system.get("comfyui_version", "?")
    device = devices[0] if devices else {}
    vram_total = device.get("vram_total")
    vram_free = device.get("vram_free")
    if vram_total and vram_free:
        device_detail = f"{device.get('name', 'gpu')} ({vram_free / 1e9:.1f}/{vram_total / 1e9:.1f} GB free)"
    else:
        device_detail = "no GPU device reported"
    checks = [Check("comfyui", OK, f"v{version} at {config.comfy.url}, {device_detail}")]
    running = len(queue.get("queue_running", []) or [])
    pending = len(queue.get("queue_pending", []) or [])
    if running or pending:
        checks.append(Check("comfyui queue", WARN, f"busy: {running} running, {pending} pending"))
    else:
        checks.append(Check("comfyui queue", OK, "idle"))
    return checks


def run_doctor(config: Config, strict: bool = False, console: Console | None = None) -> int:
    console = console or Console()
    checks: list[Check] = [
        check_python(),
        check_tools(),
        check_layout(config),
        check_disk(config),
        check_models(config),
        check_voices(config),
        check_workflows(config),
        check_compose(config),
        *check_comfy(config),
    ]
    table = Table(title=f"faceless pipeline doctor v{__version__}", box=None)
    table.add_column("check", style="bold")
    table.add_column("status")
    table.add_column("detail", overflow="fold")
    for check in checks:
        style = STATUS_STYLE.get(check.status, "white")
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)
    failures = sum(1 for check in checks if check.status == FAIL)
    warnings = sum(1 for check in checks if check.status == WARN)
    console.print(f"{len(checks)} checks: {len(checks) - failures - warnings} ok, {warnings} warn, {failures} fail")
    if failures:
        return 1
    if strict and warnings:
        return 1
    return 0

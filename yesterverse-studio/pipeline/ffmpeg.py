from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Sequence


class FFmpegError(RuntimeError):
    pass


def run(command: Sequence[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise FFmpegError(f"command failed ({result.returncode}): {' '.join(command)}\n{result.stderr[-2000:]}")
    return result


def ffmpeg_version() -> str | None:
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()[0].strip() if result.stdout else "ffmpeg"


def ffprobe_json(path: str | Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise FFmpegError(f"ffprobe failed for {path}: {result.stderr[-1000:]}")
    return json.loads(result.stdout)


def ffprobe_duration(path: str | Path) -> float:
    data = ffprobe_json(path)
    duration = data.get("format", {}).get("duration")
    if duration is None:
        raise FFmpegError(f"no duration in ffprobe output for {path}")
    return float(duration)


def write_concat_list(paths: Sequence[str | Path], list_path: str | Path) -> Path:
    list_file = Path(list_path)
    list_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in paths:
        escaped = str(Path(path).resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    list_file.write_text("\n".join(lines) + "\n")
    return list_file


def extract_last_frame(video: str | Path, destination: str | Path) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-sseof",
            "-0.25",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(destination),
        ],
        timeout=120,
    )
    if not destination.exists() or destination.stat().st_size == 0:
        raise FFmpegError(f"failed to extract last frame from {video}")
    return destination


def concat_clips(
    clips: Sequence[str | Path],
    destination: str | Path,
    duration: float,
    fps: int,
    list_path: str | Path,
    crf: int = 18,
    preset: str = "medium",
) -> Path:
    concat_list = write_concat_list(clips, list_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-an",
            "-t",
            f"{duration:.6f}",
            str(destination),
        ]
    )
    return destination


def normalize_scene(
    source: str | Path,
    destination: str | Path,
    width: int,
    height: int,
    fps: int,
    duration: float,
    crf: int,
    preset: str,
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},fps={fps},"
        f"tpad=stop_mode=clone:stop_duration=2,"
        f"trim=duration={duration:.6f},setpts=PTS-STARTPTS"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            video_filter,
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            str(destination),
        ]
    )
    return destination


def audio_segment(source: str | Path, destination: str | Path, duration: float, sample_rate: int = 48000) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    audio_filter = (
        f"aresample={sample_rate},"
        "aformat=sample_fmts=fltp:channel_layouts=stereo,"
        "apad,"
        f"atrim=0:{duration:.6f},asetpts=PTS-STARTPTS"
    )
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-af",
            audio_filter,
            "-c:a",
            "flac",
            str(destination),
        ]
    )
    return destination


def concat_audio(parts: Sequence[str | Path], destination: str | Path, list_path: str | Path) -> Path:
    concat_list = write_concat_list(parts, list_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "flac",
            str(destination),
        ]
    )
    return destination


def concat_videos(parts: Sequence[str | Path], destination: str | Path, list_path: str | Path) -> Path:
    concat_list = write_concat_list(parts, list_path)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    return destination


def mux_final(
    video: str | Path,
    audio: str | Path,
    destination: str | Path,
    audio_bitrate: str = "192k",
) -> Path:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-i",
            str(audio),
            "-c:v",
            "copy",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar",
            "48000",
            "-c:a",
            "aac",
            "-b:a",
            audio_bitrate,
            "-shortest",
            "-movflags",
            "+faststart",
            str(destination),
        ]
    )
    return destination

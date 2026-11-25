from __future__ import annotations

import math


def wan_frames(seconds: float, fps: int, minimum_frames: int = 9) -> int:
    minimum_k = max(1, math.ceil((minimum_frames - 1) / 4))
    k = max(minimum_k, math.ceil((seconds * fps - 1) / 4))
    return 1 + 4 * k


def plan_clips(target_seconds: float, fps: int, seconds_per_clip: float) -> list[int]:
    if target_seconds <= 0:
        raise ValueError("target duration must be positive")
    frames: list[int] = []
    remaining = target_seconds
    while remaining > 1e-6:
        desired = min(seconds_per_clip, remaining)
        clip = wan_frames(desired, fps)
        frames.append(clip)
        remaining -= clip / fps
        if len(frames) > 1000:
            raise ValueError("scene is too long to plan clips")
    return frames


def clip_durations(frames: list[int], fps: int) -> list[float]:
    return [count / fps for count in frames]


def render_frames(seconds: float, fps: int) -> int:
    return max(1, round(seconds * fps))


def render_duration(seconds: float, fps: int) -> float:
    return render_frames(seconds, fps) / fps


def scene_tail(scene_tail_silence: float | None, default_tail_silence: float, scene_gap: float) -> float:
    tail = scene_tail_silence if scene_tail_silence is not None else default_tail_silence
    return max(0.0, tail + scene_gap)


def clip_seed(base_seed: int, index: int) -> int:
    return (base_seed + index) % (2**32)

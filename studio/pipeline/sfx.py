"""Sound effects for scenes.

Built-in effects are synthesised from scratch (no recordings, so no copyright): cannon, pistol,
whoosh, thud, ding, tick. They are generated once into assets/sfx/_builtin/.

Your own recordings go in assets/sfx/ with a licence note beside each, exactly like music:
`<name>.license.txt` with 'source:', 'license:' and (if the licence asks for credit) 'attribution:'.
Safe sources: Freesound.org filtered to CC0, the YouTube Audio Library "Sound effects" tab.
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "sfx"
BUILTIN_DIR = SFX_DIR / "_builtin"
SR = 48000
AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".m4a")


def _lowpass(x: np.ndarray, a: float | np.ndarray) -> np.ndarray:
    """One-pole low-pass; `a` (0..1, higher = darker) may vary per sample for sweeps."""
    y = np.empty_like(x)
    acc = 0.0
    av = np.broadcast_to(np.asarray(a, np.float64), x.shape)
    for i in range(len(x)):
        acc = av[i] * acc + (1 - av[i]) * x[i]
        y[i] = acc
    return y


def _t(seconds: float) -> np.ndarray:
    return np.arange(int(SR * seconds)) / SR


def _echo(x: np.ndarray, delays=(0.09, 0.17, 0.29, 0.43), gain=0.35) -> np.ndarray:
    out = np.concatenate([x, np.zeros(int(SR * (max(delays) + 0.2)))])
    for k, d in enumerate(delays):
        n = int(SR * d)
        out[n:n + len(x)] += x * gain * (0.6 ** k)
    return out


def _cannon(rng) -> np.ndarray:
    t = _t(2.6)
    noise = rng.normal(0, 1, len(t))
    boom = _lowpass(noise, 0.985) * np.exp(-t / 0.55) * 9
    thump = np.sin(2 * np.pi * (55 * t - 18 * t ** 2)) * np.exp(-t / 0.28) * 0.9
    crack = (noise - _lowpass(noise, 0.6)) * np.exp(-t / 0.012) * 0.8
    rumble = _lowpass(rng.normal(0, 1, len(t)), 0.995) * np.exp(-t / 1.1) * 6
    return _echo(boom + thump + crack + rumble, gain=0.25)


def _pistol(rng) -> np.ndarray:
    t = _t(0.6)
    noise = rng.normal(0, 1, len(t))
    crack = (noise - _lowpass(noise, 0.5)) * np.exp(-t / 0.006) * 1.2
    body = _lowpass(noise, 0.93) * np.exp(-t / 0.06) * 2.5
    return _echo(crack + body, delays=(0.12, 0.26, 0.41), gain=0.3)


def _whoosh(rng) -> np.ndarray:
    t = _t(0.75)
    env = np.sin(np.pi * np.clip(t / 0.75, 0, 1)) ** 2
    sweep = 0.97 - 0.25 * np.sin(np.pi * t / 0.75)          # filter opens then closes
    x = _lowpass(rng.normal(0, 1, len(t)), sweep)
    return x * env * 3.0


def _thud(rng) -> np.ndarray:
    t = _t(0.45)
    body = np.sin(2 * np.pi * (90 * t - 40 * t ** 2)) * np.exp(-t / 0.07)
    slap = _lowpass(rng.normal(0, 1, len(t)), 0.8) * np.exp(-t / 0.02) * 0.9
    return body + slap


def _ding(rng) -> np.ndarray:
    t = _t(2.2)
    f = 880.0
    x = sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t / d) for r, a, d in
            ((1.0, 1.0, 0.9), (2.76, 0.45, 0.45), (5.4, 0.25, 0.22), (8.93, 0.12, 0.12)))
    return x * np.minimum(1, t / 0.003)


def _tick(rng) -> np.ndarray:
    t = _t(0.08)
    return np.sin(2 * np.pi * 2400 * t) * np.exp(-t / 0.004) + rng.normal(0, 0.3, len(t)) * np.exp(-t / 0.002)


BUILTIN = {"cannon": _cannon, "pistol": _pistol, "whoosh": _whoosh, "thud": _thud, "ding": _ding, "tick": _tick}


def _write(path: Path, x: np.ndarray) -> None:
    x = x / (np.max(np.abs(x)) or 1) * 0.89
    fade = min(len(x), int(SR * 0.02))
    x[-fade:] *= np.linspace(1, 0, fade)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def _license_fields(path: Path) -> dict[str, str]:
    lp = path.with_name(path.stem + ".license.txt")
    if not lp.is_file():
        return {}
    out = {}
    for line in lp.read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _user_path(name: str) -> Path | None:
    p = Path(name)
    if p.is_absolute():
        return p
    if p.suffix:
        return SFX_DIR / name
    for ext in AUDIO_EXT:
        if (SFX_DIR / f"{name}{ext}").is_file():
            return SFX_DIR / f"{name}{ext}"
    return None


def sfx_problem(name: str) -> str | None:
    if name in BUILTIN:
        return None
    p = _user_path(name)
    if p is None or not p.is_file():
        return f"sound effect '{name}' not found: use a built-in ({', '.join(BUILTIN)}) or a file in {SFX_DIR}."
    f = _license_fields(p)
    if not f.get("source") or not f.get("license"):
        return (f"sound effect '{name}' has no licence note: add {p.stem}.license.txt with 'source:' and 'license:' lines "
                f"(Freesound CC0 or the YouTube Audio Library are safe sources).")
    return None


def sfx_file(name: str) -> Path:
    if name in BUILTIN:
        path = BUILTIN_DIR / f"{name}.wav"
        if not path.is_file():
            _write(path, BUILTIN[name](np.random.default_rng(abs(hash(name)) % 2 ** 32)))
        return path
    problem = sfx_problem(name)
    if problem:
        raise FileNotFoundError(problem)
    return _user_path(name)


def attributions(names) -> list[str]:
    out = []
    for n in sorted(set(names)):
        if n in BUILTIN:
            continue
        p = _user_path(n)
        credit = _license_fields(p).get("attribution", "") if p else ""
        if credit and credit not in out:
            out.append(credit)
    return out

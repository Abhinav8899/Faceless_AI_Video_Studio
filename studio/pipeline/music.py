"""Music beds, licensed tracks only.

Every track in assets/music/ needs a licence note beside it, `<track name>.license.txt`:

    source: YouTube Audio Library
    url: https://studio.youtube.com/...            (where it was downloaded)
    license: YouTube Audio Library, attribution not required
    attribution:                                    (the credit line if the licence asks for one, e.g. CC BY)

A script that names a track without that note is rejected by the checker, and a non-empty
`attribution:` line is added to the YouTube description in youtube.md automatically.
"""
from __future__ import annotations

from pathlib import Path

MUSIC_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"
AUDIO_EXT = (".mp3", ".wav", ".flac", ".ogg", ".m4a")


def music_file(config, name: str) -> Path:
    p = Path(name)
    if not p.is_absolute():
        p = MUSIC_DIR / name
    if not p.is_file():
        raise FileNotFoundError(f"music track not found: {p}")
    return p


def license_path(name: str) -> Path:
    p = Path(name)
    if not p.is_absolute():
        p = MUSIC_DIR / name
    return p.with_name(p.stem + ".license.txt")


def _fields(name: str) -> dict[str, str]:
    lp = license_path(name)
    if not lp.is_file():
        return {}
    out = {}
    for line in lp.read_text().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out


def music_problem(config, name: str) -> str | None:
    p = Path(name) if Path(name).is_absolute() else MUSIC_DIR / name
    if p.suffix.lower() not in AUDIO_EXT:
        return f"music '{name}': not an audio file ({', '.join(AUDIO_EXT)})."
    if not p.is_file():
        return f"music '{name}' not found in {MUSIC_DIR}."
    f = _fields(name)
    if not f:
        return (f"music '{name}' has no licence note. Add {p.stem}.license.txt next to it with 'source:', 'license:' "
                f"and 'attribution:' lines; only use tracks you are licensed to use on YouTube.")
    if not f.get("license") or not f.get("source"):
        return f"music '{name}': the licence note needs both a 'source:' and a 'license:' line."
    return None


def attribution(name: str) -> str:
    return _fields(name).get("attribution", "")

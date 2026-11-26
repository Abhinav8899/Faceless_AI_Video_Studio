import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from pydantic import ValidationError

from pipeline.compose import (CharacterPlan, ComposeError, Library, OverlayPlan, ShotPlan, camera_box,
                              mouth_track, render)
from pipeline.script import Script

BASE = {"project": "demo", "scenes": []}


def script_with(scene: dict) -> Script:
    data = json.loads(json.dumps(BASE))
    data["scenes"] = [scene]
    return Script.model_validate(data)


# ---------------------------------------------------------------- script schema

def test_still_scene_needs_no_motion_prompt() -> None:
    s = script_with({"id": "01", "type": "still", "narration": "[nar] Rome.", "image_prompt": "forum"})
    assert s.scenes[0].type == "still"


def test_wan_scene_requires_motion_prompt() -> None:
    with pytest.raises(ValidationError, match="motion_prompt"):
        script_with({"id": "01", "narration": "x", "image_prompt": "y"})


def test_dialogue_requires_characters() -> None:
    with pytest.raises(ValidationError, match="at least one character"):
        script_with({"id": "01", "type": "dialogue", "narration": "x", "image_prompt": "y"})


def test_characters_only_in_dialogue() -> None:
    with pytest.raises(ValidationError, match="only used in dialogue"):
        script_with({"id": "01", "type": "still", "narration": "x", "image_prompt": "y",
                     "characters": [{"name": "inventor"}]})


def test_unknown_expression_rejected() -> None:
    with pytest.raises(ValidationError, match="unknown expression"):
        script_with({"id": "01", "type": "dialogue", "narration": "x", "image_prompt": "y",
                     "characters": [{"name": "inventor", "beats": [{"t": 1, "expression": "grumpy"}]}]})


def test_speaker_from_first_tag() -> None:
    s = script_with({"id": "01", "type": "dialogue", "narration": "[apprentice|temperature:0.9] Wait, what?",
                     "image_prompt": "y", "characters": [{"name": "apprentice"}]})
    assert s.scenes[0].speaker() == "apprentice"


# ---------------------------------------------------------------- camera / mouth

def test_camera_push_in_zooms_towards_focus() -> None:
    x0, y0, x1, y1 = camera_box("push_in", 0.0, 1920, 1080)
    assert (x1 - x0, y1 - y0) == (1920, 1080)
    x0, y0, x1, y1 = camera_box("push_in", 1.0, 1920, 1080, strength=0.1)
    assert abs((x1 - x0) - 1920 / 1.1) < 1e-6
    assert x0 >= 0 and x1 <= 1920 and y0 >= 0 and y1 <= 1080


def test_camera_pan_moves_across() -> None:
    a = camera_box("pan_right", 0.0, 1000, 500)
    b = camera_box("pan_right", 1.0, 1000, 500)
    assert a[0] == 0 and b[2] == pytest.approx(1000)


def test_camera_unknown_move() -> None:
    with pytest.raises(ComposeError):
        camera_box("dolly_zoom", 0.5, 100, 100)


def test_mouth_track_flaps_only_when_voiced() -> None:
    env = np.array([0.0] * 6 + [1.0] * 12 + [0.0] * 6)
    track = mouth_track(env, len(env))
    assert set(track[:6]) == {"closed"} and set(track[-6:]) == {"closed"}
    assert "open" in track[6:18] and "closed" in track[6:18]


def test_expression_beats() -> None:
    c = CharacterPlan("inventor", "talk_front", expression="neutral", beats=[(1.0, "happy"), (2.5, "laughing")])
    assert c.expression_at(0.5) == "neutral"
    assert c.expression_at(1.2) == "happy"
    assert c.expression_at(3.0) == "laughing"


# ---------------------------------------------------------------- library + render

def make_library(tmp_path: Path) -> Path:
    lib = tmp_path / "lib"
    entries = []
    for expr in ("neutral", "happy"):
        for mouth in ("closed", "open"):
            rel = f"cutouts/poses/talk_front/{expr}_{mouth}.png"
            p = lib / "hero" / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            im = Image.new("RGBA", (40, 80), (0, 0, 0, 0))
            im.paste((200, 60, 60, 255) if mouth == "open" else (60, 60, 200, 255), (10, 10, 30, 76))
            im.save(p)
            entries.append({"file": rel, "cutout": rel, "size": [40, 80], "feet_anchor": [20, 76],
                            "kind": "pose", "pose": "talk_front", "expression": expr, "mouth": mouth})
    (lib / "index.json").write_text(json.dumps({"characters": {"hero": entries}}))
    return lib


def test_library_lookup_and_fallback(tmp_path: Path) -> None:
    lib = Library(make_library(tmp_path))
    assert lib.characters() == ["hero"]
    assert lib.sprite("hero", "talk_front", "happy", "open").path.name == "happy_open.png"
    # missing expression falls back to neutral with the same mouth
    assert lib.sprite("hero", "talk_front", "angry", "open").path.name == "neutral_open.png"
    with pytest.raises(ComposeError):
        lib.sprite("hero", "cheer", "happy", "open")


def test_render_small_dialogue_shot(tmp_path: Path) -> None:
    lib = Library(make_library(tmp_path))
    bg = tmp_path / "bg.png"
    Image.new("RGB", (320, 180), (230, 215, 180)).save(bg)
    audio = tmp_path / "voice.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
                    "-ar", "16000", str(audio)], check=True)
    out = tmp_path / "shot.mp4"
    plan = ShotPlan(duration=1.2, width=160, height=90, fps=10, background=bg, audio=audio,
                    characters=[CharacterPlan("hero", "talk_front", "left", "neutral", [(0.5, "happy")], speaking=True)],
                    overlays=[OverlayPlan("label", "ROME", 0.1, 1.0, "top_left")], finish_strength=0.3)
    render(plan, lib, out, preset="ultrafast")
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,nb_frames",
                            "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.strip()
    w, h, n = probe.split(",")
    assert (int(w), int(h), int(n)) == (160, 90, 12)

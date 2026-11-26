import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.script import Script, load_script

VOICES = ["nar", "pip", "sirbumble"]

VALID = {
    "project": "demo-video",
    "style": "cinematic",
    "negative": "text, watermark",
    "defaults": {"seed": 1, "tail_silence": 0.25, "scene_gap": 0.15},
    "scenes": [
        {
            "id": "01",
            "narration": "[nar|temperature:0.7] The gate opened.\n[pip|temperature:0.9] Who goes there?",
            "image_prompt": "fortress gate in mist",
            "motion_prompt": "slow dolly forward",
            "seed": 11,
        },
        {
            "id": "02",
            "narration": "[narrator] The guard stepped back.",
            "base_image": "/tmp/pip_base.png",
            "edit_prompt": "Change only the expression to shocked.",
            "reference_image": "/tmp/pip_ref.png",
            "motion_prompt": "push in",
        },
    ],
}


def test_valid_script() -> None:
    script = Script.model_validate(VALID)
    script.validate_against(VOICES)
    assert script.voice_names() == ["nar", "pip", "narrator"]
    assert len(script.scenes) == 2


def test_unknown_voice_rejected() -> None:
    data = json.loads(json.dumps(VALID))
    data["scenes"][0]["narration"] = "[bob|temperature:0.7] Hello."
    with pytest.raises(ValueError, match="unknown voice"):
        Script.model_validate(data).validate_against(VOICES)


def test_temperature_must_be_single_decimal() -> None:
    data = json.loads(json.dumps(VALID))
    data["scenes"][0]["narration"] = "[nar|temperature:0.75] Too precise."
    with pytest.raises(ValueError, match="single-decimal"):
        Script.model_validate(data).validate_against(VOICES)


def test_temperature_range() -> None:
    data = json.loads(json.dumps(VALID))
    data["scenes"][0]["narration"] = "[nar|temperature:2.5] Too hot."
    with pytest.raises(ValueError, match="outside"):
        Script.model_validate(data).validate_against(VOICES)


def test_base_image_requires_edit_prompt() -> None:
    data = json.loads(json.dumps(VALID))
    del data["scenes"][1]["edit_prompt"]
    with pytest.raises(ValidationError, match="base_image requires edit_prompt"):
        Script.model_validate(data)


def test_edit_prompt_requires_base_image() -> None:
    data = json.loads(json.dumps(VALID))
    del data["scenes"][1]["base_image"]
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_duplicate_ids_rejected() -> None:
    data = json.loads(json.dumps(VALID))
    data["scenes"][1]["id"] = "01"
    with pytest.raises(ValidationError, match="duplicate scene id"):
        Script.model_validate(data)


def test_load_script(tmp_path: Path) -> None:
    path = tmp_path / "script.json"
    path.write_text(json.dumps(VALID))
    script = load_script(path)
    assert script.project == "demo-video"

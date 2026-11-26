import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline.checker import check_data
from pipeline.config import Config
from pipeline.script import Script

CFG = Config()
CFG.tts.voices = ["nar", "inventor", "apprentice"]
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "example_script.json"

THUMB = {"description": "d", "concept": "c", "image_prompt": "a ship", "text": "WOW"}


def base(**meta):
    m = {"titles": ["A title"], "thumbnails": [dict(THUMB) for _ in range(3)]}
    m.update(meta)
    return {"project": "demo", "style": "Rome", "meta": m,
            "scenes": [{"id": "01", "type": "still", "narration": "[nar|temperature:0.7] Rome was big and loud.",
                        "image_prompt": "forum"}]}


def test_example_script_is_clean() -> None:
    rep = check_data(json.loads(EXAMPLE.read_text()), CFG)
    assert rep.ok, rep.errors
    assert not rep.warnings, rep.warnings


def test_exactly_three_thumbnails() -> None:
    data = base(thumbnails=[dict(THUMB)])
    with pytest.raises(ValidationError, match="exactly 3"):
        Script.model_validate(data)


def test_thumbnail_needs_description() -> None:
    t = dict(THUMB); del t["description"]
    rep = check_data(base(thumbnails=[t, dict(THUMB), dict(THUMB)]), CFG)
    assert any("description" in e and "missing" in e for e in rep.errors)


def test_subscribe_overlay_needs_no_text_but_label_does() -> None:
    data = base()
    data["scenes"][0]["overlays"] = [{"kind": "subscribe", "start": 0.5}]
    Script.model_validate(data)
    data["scenes"][0]["overlays"] = [{"kind": "label", "start": 0.5}]
    with pytest.raises(ValidationError, match="needs text"):
        Script.model_validate(data)


def test_missing_cta_and_meta_warn() -> None:
    data = base(); del data["meta"]
    rep = check_data(data, CFG)
    assert rep.ok
    assert any("no 'meta'" in w for w in rep.warnings)
    assert any("like & subscribe" in w for w in rep.warnings)


def test_early_cta_warns() -> None:
    data = base()
    scenes = []
    for i in range(8):
        scenes.append({"id": f"{i:02d}", "type": "still", "image_prompt": "x",
                       "narration": "[nar|temperature:0.7] Something happened here in old Rome today."})
    scenes[0]["overlays"] = [{"kind": "subscribe"}]
    scenes[0]["narration"] = "[nar|temperature:0.7] Like and subscribe right now please, friends of history."
    data["scenes"] = scenes
    rep = check_data(data, CFG)
    assert any("first quarter" in w for w in rep.warnings)

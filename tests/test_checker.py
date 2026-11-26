import json
from pathlib import Path

from pipeline.checker import check_data, check_file
from pipeline.config import Config

CFG = Config()
CFG.tts.voices = ["nar", "inventor", "apprentice"]


def scene(**kw):
    base = {"id": "01", "type": "still", "narration": "[nar|temperature:0.7] Rome was not built in a day, they say.",
            "image_prompt": "the Roman Forum"}
    base.update(kw)
    return base


def script(*scenes, **kw):
    data = {"project": "demo", "style": "Ancient Rome", "scenes": list(scenes) or [scene()]}
    data.update(kw)
    return data


def test_valid_script_passes() -> None:
    rep = check_data(script(), CFG)
    assert rep.ok, rep.errors
    assert any("estimated video length" in i for i in rep.info)


def test_typo_field_suggests_fix() -> None:
    s = scene(); s["image_promt"] = s.pop("image_prompt")
    rep = check_data(script(s), CFG)
    assert not rep.ok
    assert any("unknown field 'image_promt'" in e and "image_prompt" in e for e in rep.errors)


def test_type_required() -> None:
    s = scene(); del s["type"]
    assert any("'type' is required" in e for e in check_data(script(s), CFG).errors)


def test_unknown_voice() -> None:
    rep = check_data(script(scene(narration="[bob|temperature:0.7] Hello there friends.")), CFG)
    assert any("unknown voice 'bob'" in e for e in rep.errors)


def test_narration_needs_tag() -> None:
    rep = check_data(script(scene(narration="No tag here at all, just words.")), CFG)
    assert any("must start with a voice tag" in e for e in rep.errors)


def test_dialogue_speaker_must_be_on_screen() -> None:
    s = scene(type="dialogue", narration="[apprentice|temperature:0.9] Wait, what happened next?",
              characters=[{"name": "inventor", "pose": "talk_front", "side": "left"}])
    rep = check_data(script(s), CFG)
    assert any("not in the scene" in e for e in rep.errors)


def test_same_side_rejected() -> None:
    s = scene(type="dialogue", narration="[inventor|temperature:0.8] Hello there, my friend!",
              characters=[{"name": "inventor", "side": "left"}, {"name": "apprentice", "side": "left"}])
    assert any("same side" in e for e in check_data(script(s), CFG).errors)


def test_bad_expression_lists_choices() -> None:
    s = scene(type="dialogue", narration="[inventor|temperature:0.8] Hello there, my friend!",
              characters=[{"name": "inventor", "expression": "excited"}])
    rep = check_data(script(s), CFG)
    assert any("unknown expression 'excited'" in e for e in rep.errors)


def test_text_in_prompt_warns() -> None:
    rep = check_data(script(scene(image_prompt="a scroll with text saying VENI VIDI VICI")), CFG)
    assert rep.ok and any("writing" in w for w in rep.warnings)


def test_invalid_json_explains(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text('{"project": "demo", "scenes": [ {"id": "01",} ]}')
    rep = check_file(p, CFG)
    assert not rep.ok and "Not valid JSON" in rep.errors[0]


def test_markdown_fence_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "s.json"
    p.write_text("```json\n" + json.dumps(script()) + "\n```")
    assert check_file(p, CFG).ok

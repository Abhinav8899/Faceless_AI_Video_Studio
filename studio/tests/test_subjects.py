"""Consistent subjects: schema, prompts, reference workflow wiring, checker rules, cache invalidation."""
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pipeline import subjects as subj
from pipeline.checker import check_data
from pipeline.config import Config
from pipeline.script import Script

CFG = Config()
CFG.tts.voices = ["nar"]
CFG.style.house = "HOUSE"
CFG.paths.workflows_dir = Path(__file__).resolve().parents[1] / "workflows"

CAESAR = {"id": "caesar", "kind": "person", "name": "Julius Caesar", "noun": "man",
          "design": "a lean Roman man of 25, short dark curly hair, strong hooked nose, olive skin, sharp dark eyes",
          "look": "white toga with a purple border", "looks": {"captive": "torn grey tunic, rope-bound wrists"}}
SHIP = {"id": "trireme", "kind": "vehicle", "name": "the pirate ship", "noun": "ship",
        "design": "a low black pirate galley with a red-striped square sail, a bronze ram and twenty oars a side"}


def scene(sid="01", **kw):
    base = {"id": sid, "type": "still", "narration": "[nar|temperature:0.7] The pirates laughed at the young Roman noble.",
            "image_prompt": "a man on the deck of a ship at dusk"}
    base.update(kw)
    return base


def data(*scenes, **kw):
    d = {"project": "demo", "style": "Ancient Rome", "subjects": [CAESAR, SHIP],
         "scenes": list(scenes) or [scene(subjects=["caesar"])]}
    d.update(kw)
    return d


def test_string_refs_become_objects() -> None:
    s = Script.model_validate(data(scene(subjects=["caesar", {"id": "trireme"}])))
    refs = s.scenes[0].subjects
    assert [r.id for r in refs] == ["caesar", "trireme"] and refs[0].look is None


@pytest.mark.parametrize("bad, msg", [
    (scene(subjects=["brutus"]), "unknown subject 'brutus'"),
    (scene(subjects=[{"id": "caesar", "look": "armour"}]), "has no look 'armour'"),
    (scene(subjects=["caesar", "caesar"]), "listed twice"),
    (scene(type="map", map={"bbox": [0, 30, 30, 45]}, subjects=["caesar"]), "still and wan pictures only"),
    (scene(base_image="x.png", edit_prompt="y", subjects=["caesar"]), "either subjects or base_image"),
])
def test_bad_refs_rejected(bad, msg) -> None:
    with pytest.raises(ValidationError, match=msg):
        Script.model_validate(data(bad))


def test_any_kind_of_subject() -> None:
    for kind in ("animal", "object", "machine", "vehicle", "building", "creature", "other"):
        s = Script.model_validate(data(subjects=[dict(SHIP, kind=kind, noun="")], scenes=[scene(subjects=["trireme"])]))
        assert s.subjects[0].detect_noun()


def test_scene_prompt_names_reference_images() -> None:
    s = Script.model_validate(data(scene(subjects=[{"id": "caesar", "look": "captive"}, "trireme"])))
    p = subj.scene_prompt("a man on the deck of a ship", s.scenes[0].subjects, s, CFG, s.style)
    assert "image 1" in p and "image 2" in p
    assert "face, hairstyle" in p and "shape, proportions" in p        # person vs thing identity
    assert "torn grey tunic" in p and p.endswith("HOUSE")


def test_portrait_prompt_is_single_plain_subject() -> None:
    s = Script.model_validate(data())
    p = subj.portrait_prompt(s.subjects[0], s, CFG)
    assert "Exactly one man" in p and "plain flat" in p and "white toga" in p
    t = subj.portrait_prompt(s.subjects[1], s, CFG)
    assert "whole ship visible" in t


def test_reference_workflow_has_one_loader_per_reference() -> None:
    wf = subj.reference_workflow(CFG, ["a.png", "b.png", "c.png"])
    loads = wf.find("LoadImage")
    assert sorted(n["inputs"]["image"] for _, n in loads) == ["a.png", "b.png", "c.png"]
    _, ref = wf.one("ReferenceMultiLatent")
    images = {k: v for k, v in ref["inputs"].items() if k.startswith("images.")}
    assert set(images) == {"images.image0", "images.image1", "images.image2"}
    assert {v[0] for v in images.values()} == {nid for nid, _ in loads}
    one = subj.reference_workflow(CFG, ["a.png"])
    assert len(one.find("LoadImage")) == 1


def test_layout_pass_starts_from_the_text_picture() -> None:
    from pipeline.workflows import validate_structure
    wf = subj.reference_workflow(CFG, ["portrait.png"], init_name="layout.png", denoise=0.8)
    validate_structure(wf.dump())
    _, sampler = wf.one("SamplerCustomAdvanced")
    enc_id = sampler["inputs"]["latent_image"][0]
    assert wf.data[enc_id]["class_type"] == "VAEEncode"
    assert wf.data[wf.data[enc_id]["inputs"]["pixels"][0]]["inputs"]["image"] == "layout.png"
    assert not wf.find("EmptyFlux2LatentImage")
    assert wf.find("BasicScheduler")[0][1]["inputs"]["denoise"] == 0.8
    s = Script.model_validate(data(scene(subjects=["caesar"])))
    lp = subj.layout_prompt("a man on a deck", s.scenes[0].subjects, s, CFG, s.style)
    assert "hooked nose" in lp and "white toga" in lp and "image 1" not in lp


def test_checker_warns_when_subject_is_drawn_from_text() -> None:
    rep = check_data(data(scene(subjects=["caesar", "trireme"]),
                          scene("02", image_prompt="close-up of Caesar laughing", subjects=["trireme"])), CFG)
    assert rep.ok, rep.errors
    assert any("mentions Julius Caesar" in w for w in rep.warnings)


def test_checker_single_use_and_unused() -> None:
    rep = check_data(data(scene(subjects=["caesar"])), CFG)
    assert any("'caesar' appears in one scene only" in w for w in rep.warnings)
    assert any("'trireme' is defined but no scene" in w for w in rep.warnings)
    assert any("subjects: caesar, trireme" in i for i in rep.info)


def test_check_is_skipped_not_fatal_without_its_models(tmp_path) -> None:
    from pipeline.likeness import LikenessChecker
    cfg = Config()
    cfg.subjects.python = tmp_path / "no-python"
    notes = []
    with LikenessChecker(cfg, log=notes.append) as c:
        assert not c.available
        assert c.score(tmp_path / "a.png", tmp_path / "b.png", "man", True) is None
    assert any("likeness check off" in n for n in notes)
    cfg.subjects.check = False
    assert not LikenessChecker(cfg).available


def test_redesigned_subject_redraws_its_scenes(tmp_path) -> None:
    from rich.console import Console
    from pipeline.studio import invalidate_changed
    cfg = Config()
    cfg.paths.runs_dir = tmp_path
    old = Script.model_validate(data(scene(subjects=["caesar"]), scene("02", subjects=["trireme"]), scene("03")))
    work = tmp_path / "demo" / "work"
    work.mkdir(parents=True)
    (work / "script.json").write_text(old.model_dump_json())
    new = json.loads(old.model_dump_json())
    new["subjects"][0]["design"] += ", a thin scar on the left cheek"
    changed = invalidate_changed(cfg, Script.model_validate(new), Console(quiet=True))
    assert changed == ["01"]

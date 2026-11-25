"""Strict script checking with plain-English messages.

check_file() never raises for a bad script: it returns a Report with errors (block the render),
warnings (render goes ahead) and an estimate of length and render time.
"""
from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pipeline.config import Config
from pipeline.script import EXPRESSIONS, TAG_RE, Scene, Script

WORDS_PER_SECOND = 2.6          # Qwen3-TTS narration pace, measured on our voices
SECONDS = {"still": 25, "dialogue": 25, "wan_per_clip": 110, "audio_factor": 1.6}

FIELD_NAMES = {
    "script": ["project", "style", "negative", "defaults", "meta", "scenes"],
    "meta": ["angle", "hook", "titles", "description", "tags", "thumbnails", "retention_notes"],
    "thumbnail": ["description", "concept", "image_prompt", "text", "text_position", "character", "seed"],
    "thumb_character": ["name", "pose", "expression", "side"],
    "scene": list(Scene.model_fields),
    "character": ["name", "pose", "side", "expression", "beats", "height", "flip"],
    "overlay": ["kind", "text", "start", "end", "position"],
    "beat": ["t", "expression"],
    "defaults": ["seed", "tail_silence", "scene_gap"],
}


@dataclass
class Report:
    path: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    script: Script | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    def text(self) -> str:
        lines = [f"Script check: {self.path}", "RESULT: " + ("OK, ready to render" if self.ok else f"REJECTED ({len(self.errors)} error(s))"), ""]
        if self.errors:
            lines.append("ERRORS (fix these, then drop the script in the inbox again):")
            lines += [f"  - {e}" for e in self.errors] + [""]
        if self.warnings:
            lines.append("WARNINGS (the video will still render):")
            lines += [f"  - {w}" for w in self.warnings] + [""]
        if self.info:
            lines.append("SUMMARY:")
            lines += [f"  {i}" for i in self.info]
        return "\n".join(lines).rstrip() + "\n"


def _where(loc: tuple, raw: dict) -> str:
    parts: list[str] = []
    i = 0
    while i < len(loc):
        key = loc[i]
        if key == "scenes" and i + 1 < len(loc) and isinstance(loc[i + 1], int):
            idx = loc[i + 1]
            sid = None
            try:
                sid = raw["scenes"][idx].get("id")
            except (KeyError, IndexError, TypeError, AttributeError):
                pass
            parts.append(f"scene #{idx + 1}" + (f" (id '{sid}')" if sid else ""))
            i += 2
            continue
        if isinstance(key, int):
            parts[-1] = parts[-1] + f" #{key + 1}" if parts else f"#{key + 1}"
        else:
            parts.append(str(key))
        i += 1
    return " > ".join(parts) or "script"


def _context(loc: tuple) -> str:
    names = [k for k in loc if isinstance(k, str)]
    parent = names[-2] if len(names) >= 2 else None
    if names and names[0] == "meta":
        return {"meta": "meta", "thumbnails": "thumbnail", "character": "thumb_character"}.get(parent or "meta", "meta")
    return {"characters": "character", "overlays": "overlay", "beats": "beat", "defaults": "defaults",
            "scenes": "scene"}.get(parent or "", "script" if len(names) <= 1 else "scene")


def _pydantic_errors(exc: ValidationError, raw: dict) -> list[str]:
    out = []
    for err in exc.errors():
        loc = tuple(err.get("loc", ()))
        where = _where(loc, raw)
        kind = err.get("type", "")
        if kind == "extra_forbidden":
            name = str(loc[-1])
            options = FIELD_NAMES.get(_context(loc), [])
            guess = difflib.get_close_matches(name, options, n=1)
            hint = f" Did you mean '{guess[0]}'?" if guess else f" Allowed: {', '.join(options)}."
            out.append(f"{_where(loc[:-1], raw)}: unknown field '{name}'.{hint}")
        elif kind == "missing":
            out.append(f"{where}: required field is missing.")
        elif kind == "literal_error":
            expected = err.get("ctx", {}).get("expected", "")
            out.append(f"{where}: '{err.get('input')}' is not allowed; use one of {expected}.")
        elif kind == "string_pattern_mismatch" and loc == ("project",):
            out.append(f"project: '{err.get('input')}' must be lowercase letters, digits and dashes only, e.g. 'caesar-and-the-pirates'.")
        elif kind == "string_pattern_mismatch" and loc[-1:] == ("id",):
            out.append(f"{where}: scene ids may only use letters, digits, '-' and '_' (got '{err.get('input')}').")
        elif kind == "value_error":
            msg = str(err.get("msg", "")).removeprefix("Value error, ")
            msg = re.sub(r"^scene [^:]+: ", "", msg)
            if msg.startswith("wan scenes need") and isinstance(err.get("input"), dict) and "type" not in err["input"]:
                continue                                    # already reported as "'type' is required"
            out.append(f"{where}: {msg}")
        else:
            out.append(f"{where}: {err.get('msg')} (got {json.dumps(err.get('input'))[:60]})")
    return out


def estimate_seconds(narration: str) -> float:
    text = TAG_RE.sub(" ", narration)
    words = len(re.findall(r"[A-Za-z0-9']+", text))
    return max(1.0, words / WORDS_PER_SECOND)


def check_data(raw: Any, config: Config, library=None, path: str = "script") -> Report:
    rep = Report(path)
    if not isinstance(raw, dict):
        rep.errors.append("The file must contain one JSON object (starting with '{').")
        return rep
    for i, scene in enumerate(raw.get("scenes", []) or []):
        if isinstance(scene, dict) and "type" not in scene:
            rep.errors.append(f"scene #{i + 1} (id '{scene.get('id', '?')}'): 'type' is required; use \"still\", \"dialogue\" or \"wan\".")
    try:
        script = Script.model_validate(raw)
    except ValidationError as exc:
        rep.errors += _pydantic_errors(exc, raw)
        # voice tags can be checked even when the structure is broken, so all problems show up in one pass
        allowed = {v.lower() for v in config.tts.voices} | {"narrator"}
        for i, sc in enumerate(raw.get("scenes", []) or []):
            if not isinstance(sc, dict) or not isinstance(sc.get("narration"), str):
                continue
            label = f"scene #{i + 1} (id '{sc.get('id', '?')}')"
            if not TAG_RE.match(sc["narration"].strip()):
                rep.errors.append(f"{label}: narration must start with a voice tag such as [nar|temperature:0.7].")
            for tag in TAG_RE.findall(sc["narration"]):
                name = tag.split("|", 1)[0].split(":")[-1].strip().lower()
                if name and name not in allowed:
                    rep.errors.append(f"{label}: unknown voice '{name}'. Voices available: {', '.join(config.tts.voices)}.")
        return rep
    try:
        script.validate_against(config.tts.voices)
    except ValueError as exc:
        rep.errors.append(f"{exc} Voices available: {', '.join(config.tts.voices)}.")
    if library is not None:
        try:
            script.validate_characters(library)
        except ValueError as exc:
            rep.errors.append(str(exc))

    total = 0.0
    wan_clips = 0
    types = {"still": 0, "dialogue": 0, "wan": 0}
    for scene in script.scenes:
        sid = f"scene '{scene.id}'"
        types[scene.type] += 1
        if not TAG_RE.match(scene.narration.strip()):
            rep.errors.append(f"{sid}: narration must start with a voice tag such as [nar|temperature:0.7].")
        est = estimate_seconds(scene.narration)
        total += est + 0.45
        if scene.type == "wan":
            wan_clips += max(1, int(est // 5) + 1)
        if est < 1.8:
            rep.warnings.append(f"{sid}: very short (~{est:.1f} s). Captions and camera moves need ~3 s to read well.")
        if est > 14:
            rep.warnings.append(f"{sid}: long (~{est:.0f} s on one picture). Consider splitting it into 2-3 scenes.")
        speaker = scene.speaker()
        if scene.type == "dialogue":
            names = [c.name for c in scene.characters]
            if speaker in ("nar", "narrator", None):
                rep.warnings.append(f"{sid}: dialogue scene voiced by the narrator, so nobody's mouth will move.")
            elif speaker not in names:
                rep.errors.append(f"{sid}: the voice is '{speaker}' but that character is not in the scene ({', '.join(names)}). Add them or change the voice tag.")
            sides = [c.side for c in scene.characters]
            if len(sides) != len(set(sides)):
                rep.errors.append(f"{sid}: two characters are on the same side ('{sides[0]}'); use left and right.")
            for c in scene.characters:
                for b in c.beats:
                    if b.t > est + 0.5:
                        rep.warnings.append(f"{sid}: {c.name}'s expression change at {b.t}s is after the scene probably ends (~{est:.1f} s).")
        elif speaker in ("inventor", "apprentice"):
            rep.warnings.append(f"{sid}: {speaker} speaks in a {scene.type} scene, so the mascot is heard but not seen. Use a dialogue scene to show them.")
        for ov in scene.overlays:
            if ov.start > est - 0.8:
                rep.warnings.append(f"{sid}: caption '{ov.text}' starts at {ov.start}s but the scene is only ~{est:.1f} s long.")
        prompt = (scene.image_prompt or scene.edit_prompt or "").lower()
        if re.search(r"\b(text|words|caption|title|letters|sign that says)\b", prompt) and "no text" not in prompt:
            rep.warnings.append(f"{sid}: the image prompt asks for writing; image models draw garbled text. Use an overlay instead.")
        if scene.base_image and not Path(scene.base_image).is_absolute() and not (config.paths.refs_dir / scene.base_image).is_file():
            rep.errors.append(f"{sid}: base_image '{scene.base_image}' not found in {config.paths.refs_dir}.")

    # writing for the voice (cinematic-film skill): digits and abbreviations are misread by TTS
    for scene in script.scenes:
        spoken = TAG_RE.sub(" ", scene.narration)
        if re.search(r"\d", spoken):
            rep.warnings.append(f"scene '{scene.id}': narration contains digits ({', '.join(sorted(set(re.findall(r'[0-9][0-9,.]*', spoken))))}); "
                                "write numbers as words (\"seventy-five BC\") so the voice reads them correctly.")
    # camera language (huashu-art-motion skill): never three push-ins in a row
    streak = 0
    for scene in script.scenes:
        move = scene.camera or ("push_in" if scene.type in ("still", "dialogue") else None)
        streak = streak + 1 if move == "push_in" else 0
        if streak == 3:
            rep.warnings.append(f"scene '{scene.id}': third push_in in a row; alternate with pull_out, pan_left/pan_right or static so it does not feel like a slideshow.")

    # packaging and retention (YouTube)
    starts, t_acc = [], 0.0
    for scene in script.scenes:
        starts.append(t_acc)
        t_acc += estimate_seconds(scene.narration) + 0.45
    meta = script.meta
    if meta is None:
        rep.warnings.append("no 'meta' block: no title options or description, and the 3 thumbnails will be plain fallbacks made from scene pictures.")
    else:
        if len(meta.titles) < 3:
            rep.warnings.append(f"meta.titles has {len(meta.titles)} option(s); 3 lets you A/B test.")
        for title in meta.titles:
            if len(title) > 70:
                rep.warnings.append(f"title is {len(title)} characters; YouTube cuts titles around 60-70: \"{title[:70]}...\"")
        for i, t in enumerate(meta.thumbnails, 1):
            if len(t.text.split()) > 4:
                rep.warnings.append(f"thumbnail {i}: text has {len(t.text.split())} words; 1-4 big words read best on a phone.")
            if re.search(r"\b(text|words|caption|title|letters)\b", t.image_prompt.lower()):
                rep.warnings.append(f"thumbnail {i}: image_prompt mentions text; the big text is added by the studio, the picture must have none.")
        if not meta.description.strip():
            rep.warnings.append("meta.description is empty.")
    chapters = [(starts[i], s.chapter) for i, s in enumerate(script.scenes) if s.chapter]
    if chapters:
        if len(chapters) + (0 if script.scenes[0].chapter else 1) < 3:
            rep.warnings.append("YouTube shows chapters only when there are at least 3 (the first starting at 0:00).")
        bounds = [c[0] for c in chapters] + [t_acc]
        for (start, name), end in zip(chapters, bounds[1:]):
            if end - start < 10:
                rep.warnings.append(f"chapter '{name}' is only ~{end - start:.0f} s; YouTube needs every chapter to be at least 10 s.")
    first = script.scenes[0]
    if first.type == "dialogue":
        rep.warnings.append("the video opens on the mascots; open on the most surprising moment of the story (the hook), then bring them in.")
    if estimate_seconds(first.narration) > 9:
        rep.warnings.append(f"the first scene is ~{estimate_seconds(first.narration):.0f} s; the hook should land within the first 5-8 seconds.")
    cta = [i for i, s in enumerate(script.scenes) if any(o.kind == "subscribe" for o in s.overlays)]
    if not cta:
        rep.warnings.append("no like & subscribe moment: add a 'subscribe' overlay (5 s badge) to one scene whose narration asks viewers to like and subscribe, right after a big payoff.")
    else:
        sc = script.scenes[cta[0]]
        if len(cta) > 1:
            rep.warnings.append(f"{len(cta)} subscribe badges; one is enough (more feels pushy).")
        if cta[0] < len(script.scenes) * 0.25:
            rep.warnings.append(f"like & subscribe in scene '{sc.id}', in the first quarter; early asks make viewers leave. Put it after a payoff, in the second half.")
        if not re.search(r"\bsubscrib", sc.narration, re.I):
            rep.warnings.append(f"scene '{sc.id}' shows the subscribe badge but the narration never asks viewers to like and subscribe.")
        badge = next(o for o in sc.overlays if o.kind == "subscribe")
        if estimate_seconds(sc.narration) < badge.start + 4.5:
            rep.warnings.append(f"scene '{sc.id}' is ~{estimate_seconds(sc.narration):.1f} s; it will be held silently until the 5 s subscribe badge finishes. A ~14-18 word line fills it better.")

    n = len(script.scenes)
    if not script.style.strip():
        rep.warnings.append("'style' is empty. Put the era and place there (e.g. \"Ancient Rome, 1st century BC\") so clothes and objects stay period-correct.")
    if types["wan"] > max(2, n * 0.3):
        rep.warnings.append(f"{types['wan']} of {n} scenes use Wan video; that is slow (~2 min each) and Wan can smear. Prefer 'still' for most scenes.")
    est_render = (types["still"] + types["dialogue"]) * SECONDS["still"] + wan_clips * SECONDS["wan_per_clip"] + total * SECONDS["audio_factor"]
    rep.info += [
        f"project: {script.project}",
        f"scenes: {n} ({types['still']} still, {types['dialogue']} dialogue, {types['wan']} wan)",
        f"estimated video length: ~{total / 60:.1f} min ({total:.0f} s)",
        f"estimated render time: ~{est_render / 60:.0f} min",
        f"voices: {', '.join(script.voice_names())}",
        f"titles: {' | '.join(script.meta.titles) if script.meta else '-'}",
        f"thumbnails: {len(script.meta.thumbnails) if script.meta else '3 fallbacks'}; chapters: {len(chapters) or '-'}",
    ]
    rep.script = script
    return rep


def check_file(path: str | Path, config: Config, library=None) -> Report:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        rep = Report(str(path)); rep.errors.append(f"Cannot read the file: {exc}"); return rep
    text = text.strip()
    if text.startswith("```"):                       # tolerate a pasted markdown code block
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text)
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        rep = Report(str(path))
        line = text.splitlines()[exc.lineno - 1] if 0 < exc.lineno <= len(text.splitlines()) else ""
        rep.errors.append(f"Not valid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}: {line.strip()[:80]}")
        rep.errors.append("Common causes: a missing comma between items, a trailing comma before } or ], or a quote (\") inside text that is not escaped.")
        return rep
    return check_data(raw, config, library, str(path))

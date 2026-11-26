from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SCENE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TAG_RE = re.compile(r"\[([^\[\]]+)\]")
PARAM_RE = re.compile(r"^([A-Za-z_]+):(.*)$")
TEMPERATURE_RE = re.compile(r"^[0-9]+\.[0-9]$")

SceneType = Literal["wan", "still", "dialogue", "map"]
CameraMove = Literal["push_in", "pull_out", "pan_left", "pan_right", "static"]
EXPRESSIONS = ("neutral", "happy", "laughing", "smug", "angry", "sad", "scared", "shocked", "thinking")


class SceneDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int | None = Field(default=None, ge=0)
    tail_silence: float = Field(default=0.25, ge=0.0)
    scene_gap: float = Field(default=0.15, ge=0.0)


class Beat(BaseModel):
    """Switch a character's expression `t` seconds into the scene."""
    model_config = ConfigDict(extra="forbid")
    t: float = Field(ge=0.0)
    expression: str


class CharacterSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)                         # character library id, e.g. "inventor"
    pose: str = "talk_front"
    side: Literal["left", "center", "right"] = "left"
    expression: str = "neutral"
    beats: list[Beat] = Field(default_factory=list)
    height: float = Field(default=0.80, gt=0.1, le=1.2)     # fraction of frame height
    flip: bool = False


class Overlay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["label", "date", "title", "subscribe", "stat", "headline"] = "label"
    text: str = Field(default="", max_length=60)             # not used by "subscribe" (fixed LIKE + SUBSCRIBE badge)
    label: str = Field(default="", max_length=80)            # stat: caption under the number; headline: masthead line
    start: float = Field(default=0.3, ge=0.0)
    end: float | None = None                                 # None = until the scene ends ("subscribe": 5 s)

    @model_validator(mode="after")
    def check_text(self) -> "Overlay":
        if self.kind != "subscribe" and not self.text.strip():
            raise ValueError(f"a '{self.kind}' overlay needs text")
        return self
    position: Literal["top_left", "top_right", "top", "bottom", "center"] = "top_left"


class SoundEffect(BaseModel):
    """A sound at `at` seconds into the scene: a built-in (cannon, pistol, whoosh, thud, ding, tick)
    or a licensed file in assets/sfx."""
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    at: float = Field(default=0.0, ge=0.0)
    volume_db: float = Field(default=-8.0, ge=-40.0, le=6.0)


class MapPlace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-85, le=85)
    at: float | None = Field(default=None, ge=0.0)       # seconds; default: when the route reaches it


class MapRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=40)
    lon: float = Field(ge=-180, le=180)
    lat: float = Field(ge=-85, le=85)


class MapSpec(BaseModel):
    """A code-drawn parchment map: the camera eases in to `bbox`, the route draws itself, pins pop in."""
    model_config = ConfigDict(extra="forbid")
    bbox: list[float] = Field(min_length=4, max_length=4)          # [lon_min, lat_min, lon_max, lat_max] final view
    start_bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)  # opening view (default 1.7x wider)
    places: list[MapPlace] = Field(default_factory=list, max_length=8)
    route: list[list[float]] = Field(default_factory=list)          # [[lon, lat], ...]
    route_start: float | None = Field(default=None, ge=0.0)
    route_end: float | None = Field(default=None, ge=0.0)
    regions: list[MapRegion] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def check_geo(self) -> "MapSpec":
        for box in [self.bbox] + ([self.start_bbox] if self.start_bbox else []):
            if not (box[0] < box[2] and box[1] < box[3]):
                raise ValueError(f"map bbox {box} must be [lon_min, lat_min, lon_max, lat_max]")
        for pt in self.route:
            if len(pt) != 2:
                raise ValueError(f"map route point {pt} must be [lon, lat]")
        if len(self.route) == 1:
            raise ValueError("a map route needs at least 2 points")
        return self


SubjectKind = Literal["person", "animal", "creature", "object", "machine", "vehicle", "building", "other"]
SUBJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
DEFAULT_NOUN = {"person": "person", "animal": "animal", "creature": "creature", "object": "object",
                "machine": "machine", "vehicle": "vehicle", "building": "building", "other": "object"}


class Subject(BaseModel):
    """Something that must look the same in every scene it appears in: a person, an animal, a tool,
    a machine, a ship, a building... The studio draws one reference portrait of it and builds every
    scene that lists it from that portrait."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=40, pattern=SUBJECT_ID_RE.pattern)   # e.g. "caesar", "wright_flyer"
    kind: SubjectKind = "person"
    name: str = Field(min_length=1, max_length=60)              # "Julius Caesar", "the Wright Flyer"
    noun: str = Field(default="", max_length=40)                # what it is in 1-3 plain words ("man", "biplane"); used to find it in pictures
    design: str = Field(min_length=10, max_length=600)          # the fixed look: never changes between scenes
    look: str = Field(default="", max_length=300)               # default clothes / state / paint shown in the portrait
    looks: dict[str, str] = Field(default_factory=dict)         # other named looks: {"captive": "torn grey tunic, rope-bound wrists"}
    reference_image: str | None = None                          # your own portrait (in refs/) instead of a generated one

    @model_validator(mode="after")
    def check_looks(self) -> "Subject":
        for key, text in self.looks.items():
            if not SUBJECT_ID_RE.match(key):
                raise ValueError(f"subject {self.id}: look name '{key}' must be lowercase letters, digits or _")
            if not text.strip():
                raise ValueError(f"subject {self.id}: look '{key}' needs a description")
        return self

    def detect_noun(self) -> str:
        return (self.noun or DEFAULT_NOUN[self.kind]).strip()


class SubjectRef(BaseModel):
    """A subject in a scene: "caesar" or {"id": "caesar", "look": "captive"}."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    look: str | None = None                                      # a key of the subject's `looks`; None = its default look


def _subject_refs(value):
    if isinstance(value, list):
        return [{"id": v} if isinstance(v, str) else v for v in value]
    return value


class ThumbCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    pose: str = "talk_front"
    expression: str = "shocked"
    side: Literal["left", "right"] = "right"


class Thumbnail(BaseModel):
    """One thumbnail option: a generated picture + optional mascot + big text."""
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1)                   # what the thumbnail shows, in plain words
    concept: str = Field(min_length=1)                       # why this thumbnail gets the click
    image_prompt: str = Field(min_length=1)                  # what the image model draws (no text)
    text: str = Field(default="", max_length=32)             # 0-4 big words; "" = no text
    text_position: Literal["left", "right", "top", "bottom"] | None = None
    character: ThumbCharacter | None = None
    subjects: list[SubjectRef] = Field(default_factory=list, max_length=3)   # drawn from their reference portraits
    seed: int | None = Field(default=None, ge=0)

    @field_validator("subjects", mode="before")
    @classmethod
    def _refs(cls, v):
        return _subject_refs(v)


class Meta(BaseModel):
    """YouTube packaging: written by the scriptwriter, used for thumbnails and youtube.md."""
    model_config = ConfigDict(extra="forbid")
    angle: str = ""                                          # the one-sentence promise / curiosity gap
    hook: str = ""                                           # what the first 5 seconds do
    titles: list[str] = Field(default_factory=list, max_length=5)
    description: str = ""
    tags: list[str] = Field(default_factory=list, max_length=30)
    thumbnails: list[Thumbnail] = Field(default_factory=list)
    retention_notes: list[str] = Field(default_factory=list)  # open loops, re-hooks, payoffs (for the record)

    @model_validator(mode="after")
    def check_thumbnails(self) -> "Meta":
        if len(self.thumbnails) != 3:
            raise ValueError(f"meta.thumbnails must contain exactly 3 thumbnail options (got {len(self.thumbnails)})")
        for i, t in enumerate(self.thumbnails, 1):
            if t.character and t.character.expression not in EXPRESSIONS:
                raise ValueError(f"thumbnail {i}: unknown expression '{t.character.expression}' (use one of {', '.join(EXPRESSIONS)})")
        if not self.titles:
            raise ValueError("meta.titles needs at least one title (3 options recommended)")
        return self


class Scene(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, pattern=SCENE_ID_RE.pattern)
    type: SceneType = "wan"
    chapter: str | None = Field(default=None, max_length=60)   # YouTube chapter title starting at this scene
    narration: str = Field(min_length=1)
    image_prompt: str | None = None
    motion_prompt: str | None = None
    base_image: str | None = None
    edit_prompt: str | None = None
    reference_image: str | None = None
    seed: int | None = Field(default=None, ge=0)
    tail_silence: float | None = Field(default=None, ge=0.0)
    use_global_style: bool = True
    camera: CameraMove | None = None                         # still/dialogue; default push_in
    characters: list[CharacterSpec] = Field(default_factory=list)
    overlays: list[Overlay] = Field(default_factory=list)
    map: MapSpec | None = None                                # type "map" only
    sfx: list[SoundEffect] = Field(default_factory=list, max_length=8)
    subjects: list[SubjectRef] = Field(default_factory=list, max_length=3)   # ids from the script's `subjects`

    @field_validator("subjects", mode="before")
    @classmethod
    def _refs(cls, v):
        return _subject_refs(v)

    @model_validator(mode="after")
    def check_prompt_contract(self) -> "Scene":
        if self.subjects:
            if self.type not in ("still", "wan"):
                raise ValueError(f"scene {self.id}: subjects are drawn into still and wan pictures only (not {self.type})")
            if self.base_image:
                raise ValueError(f"scene {self.id}: use either subjects or base_image, not both")
            ids = [r.id for r in self.subjects]
            if len(ids) != len(set(ids)):
                raise ValueError(f"scene {self.id}: a subject is listed twice")
        if self.base_image:
            if not self.edit_prompt:
                raise ValueError(f"scene {self.id}: base_image requires edit_prompt")
        elif not self.image_prompt and self.type != "map":
            raise ValueError(f"scene {self.id}: image_prompt is required when base_image is absent")
        if self.edit_prompt and not self.base_image:
            raise ValueError(f"scene {self.id}: edit_prompt requires base_image")
        if self.reference_image and not self.base_image:
            raise ValueError(f"scene {self.id}: reference_image requires base_image")
        if self.type == "map" and self.map is None:
            raise ValueError(f"scene {self.id}: map scenes need a 'map' block (bbox, places, route)")
        if self.map is not None and self.type != "map":
            raise ValueError(f"scene {self.id}: a 'map' block is only used by type \"map\" scenes")
        if self.type == "wan" and not self.motion_prompt:
            raise ValueError(f"scene {self.id}: wan scenes need a motion_prompt")
        if self.type == "dialogue" and not self.characters:
            raise ValueError(f"scene {self.id}: dialogue scenes need at least one character")
        if self.type != "dialogue" and self.characters:
            raise ValueError(f"scene {self.id}: characters are only used in dialogue scenes")
        if len(self.characters) > 2:
            raise ValueError(f"scene {self.id}: at most two characters per dialogue scene")
        for c in self.characters:
            for expr in [c.expression] + [b.expression for b in c.beats]:
                if expr not in EXPRESSIONS:
                    raise ValueError(f"scene {self.id}: unknown expression '{expr}' (use one of {', '.join(EXPRESSIONS)})")
        for ov in self.overlays:
            if ov.end is not None and ov.end <= ov.start:
                raise ValueError(f"scene {self.id}: overlay '{ov.text}' ends before it starts")
        return self

    def speaker(self) -> str | None:
        """Voice of the first tag in the narration ("narrator"/"nar" if untagged)."""
        tags = TAG_RE.findall(self.narration)
        if not tags:
            return None
        name = tags[0].split("|", 1)[0]
        if ":" in name:
            name = name.split(":", 1)[1]
        return name.strip().lower() or None


class Script(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(pattern=PROJECT_RE.pattern)
    style: str = ""
    negative: str = ""
    defaults: SceneDefaults = Field(default_factory=SceneDefaults)
    meta: Meta | None = None
    music: str | None = None                                  # file in assets/music (optional score, ducked under the voice)
    music_volume_db: float = Field(default=-24.0, ge=-60.0, le=0.0)
    auto_sfx: bool = True                                     # thud under headline slams, whoosh on map moves
    subjects: list[Subject] = Field(default_factory=list, max_length=12)   # things that must stay consistent
    scenes: list[Scene] = Field(min_length=1)

    @model_validator(mode="after")
    def check_scene_ids(self) -> "Script":
        seen: set[str] = set()
        for scene in self.scenes:
            if scene.id in seen:
                raise ValueError(f"duplicate scene id: {scene.id}")
            seen.add(scene.id)
        subjects = {}
        for s in self.subjects:
            if s.id in subjects:
                raise ValueError(f"duplicate subject id: {s.id}")
            subjects[s.id] = s
        refs = [(f"scene {sc.id}", r) for sc in self.scenes for r in sc.subjects]
        refs += [(f"thumbnail {i}", r) for i, t in enumerate(self.meta.thumbnails if self.meta else [], 1) for r in t.subjects]
        for where, r in refs:
            if r.id not in subjects:
                raise ValueError(f"{where}: unknown subject '{r.id}' (defined: {', '.join(subjects) or 'none'})")
            if r.look and r.look not in subjects[r.id].looks:
                have = ", ".join(subjects[r.id].looks) or "none"
                raise ValueError(f"{where}: subject '{r.id}' has no look '{r.look}' (its looks: {have})")
        return self

    def subject(self, sid: str) -> Subject:
        return next(s for s in self.subjects if s.id == sid)

    def voice_names(self) -> list[str]:
        names: list[str] = []
        for scene in self.scenes:
            for tag in TAG_RE.findall(scene.narration):
                name_part = tag.split("|", 1)[0]
                if ":" in name_part:
                    _, name_part = name_part.split(":", 1)
                name = name_part.strip().lower()
                if name and name not in names:
                    names.append(name)
        return names

    def validate_against(self, voices: Sequence[str]) -> None:
        allowed = {voice.lower() for voice in voices} | {"narrator"}
        for scene in self.scenes:
            for tag in TAG_RE.findall(scene.narration):
                parts = tag.split("|")
                name_part = parts[0]
                if ":" in name_part:
                    _, name_part = name_part.split(":", 1)
                name = name_part.strip().lower()
                if not name:
                    continue
                if name not in allowed:
                    raise ValueError(f"scene {scene.id}: unknown voice '{name}' (allowed: {sorted(allowed)})")
                for param in parts[1:]:
                    self._validate_param(scene.id, param.strip())

    def validate_characters(self, library) -> None:
        """Check dialogue characters and poses exist in the character library."""
        known = set(library.characters())
        for i, t in enumerate(self.meta.thumbnails if self.meta else [], 1):
            c = t.character
            if c is None:
                continue
            if c.name not in known:
                raise ValueError(f"thumbnail {i}: character '{c.name}' not in library (have: {sorted(known)})")
            if not library.has_pose(c.name, c.pose):
                raise ValueError(f"thumbnail {i}: {c.name} has no pose '{c.pose}' (have: {library.poses(c.name)})")
        for scene in self.scenes:
            for c in scene.characters:
                if c.name not in known:
                    raise ValueError(f"scene {scene.id}: character '{c.name}' not in library (have: {sorted(known)})")
                if not library.has_pose(c.name, c.pose):
                    raise ValueError(f"scene {scene.id}: {c.name} has no pose '{c.pose}' (have: {library.poses(c.name)})")

    @staticmethod
    def _validate_param(scene_id: str, param: str) -> None:
        match = PARAM_RE.match(param)
        if not match:
            raise ValueError(f"scene {scene_id}: malformed tag parameter '{param}'")
        key = match.group(1).lower()
        value = match.group(2).strip()
        if key == "temperature":
            if not TEMPERATURE_RE.match(value):
                raise ValueError(f"scene {scene_id}: temperature '{value}' must be a single-decimal number")
            temperature = float(value)
            if not 0.1 <= temperature <= 2.0:
                raise ValueError(f"scene {scene_id}: temperature '{value}' outside 0.1-2.0")
        elif key == "seed":
            if not value.isdigit():
                raise ValueError(f"scene {scene_id}: seed '{value}' must be a non-negative integer")


def load_script(path: str | Path) -> Script:
    data = json.loads(Path(path).read_text())
    return Script.model_validate(data)

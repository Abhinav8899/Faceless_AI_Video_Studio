# Script format (Studio 1.2)

One JSON object. Unknown fields are rejected (a typo like `image_promt` is an error, with a suggestion).
The house art style is added automatically from `config.yaml`; the script's `style` only describes the era.

## Top level

| field | required | meaning |
|---|---|---|
| `project` | yes | lowercase id with dashes; the output folder name. Re-using it re-renders only changed scenes |
| `style` | recommended | era and place, e.g. "Ancient Rome, 75 BC: togas, galleys, oil lamps" |
| `negative` | no | extra things Wan should avoid (a default is in config.yaml) |
| `defaults` | no | `seed` (same seed + same prompt = identical picture), `tail_silence` (0.3), `scene_gap` (0.15) |
| `scenes` | yes | list of scenes, played in order |
| `music` | no | a licensed track in `assets/music/` (needs `<name>.license.txt`), looped and ducked under the voice |
| `music_volume_db` | no | music level, default -24 |
| `auto_sfx` | no | default true: a thud under each headline slam and a whoosh on each map move |
| `subjects` | recommended | the people and things that must look the same in every scene (see Subjects below) |

## Scene

| field | for | meaning |
|---|---|---|
| `id` | all, required | unique, e.g. "01" |
| `type` | all, required | `still`, `dialogue`, `wan` or `map` |
| `narration` | all, required | starts with a voice tag: `[nar|temperature:0.7]` (other voices: names in `tts.voices` in config.yaml). The scene lasts as long as the narration |
| `image_prompt` | all | what is in the picture (dialogue: the empty background; people are removed automatically) |
| `camera` | still, dialogue | `push_in` (default), `pull_out`, `pan_left`, `pan_right`, `static` |
| `characters` | dialogue, required | 1-2 mascots, see below |
| `motion_prompt` | wan, required | one simple action, ideally ending "the camera stays still" |
| `overlays` | any | captions, see below |
| `map` | map, required | the map to draw, see below (map scenes have no image_prompt) |
| `sfx` | any | sound effects, see below |
| `subjects` | still, wan | which subjects are in the picture: `["caesar"]` or `[{"id": "caesar", "look": "captive"}]` (max 3) |
| `seed` | any | override the picture seed for this scene (use to get a different picture) |
| `base_image` + `edit_prompt` (+ `reference_image`) | still, wan | edit an existing picture in `refs/` instead of generating from text |
| `tail_silence` | any | extra pause after this scene's narration |

## Subjects (consistent people and things)

The main subject of a video must not change from scene to scene: the same face for a person, the same shape,
colours and details for a tool, machine, ship, animal or building. Define each one once at the top level:

```json
{ "id": "caesar", "kind": "person", "name": "Julius Caesar", "noun": "man",
  "design": "a lean Roman man of 25, short dark curly hair, strong hooked nose, clean-shaven, olive skin, sharp dark eyes, thin build",
  "look": "white wool toga with a purple border, leather sandals",
  "looks": { "captive": "torn grey tunic, rope-bound wrists, bare feet" } }
```

| field | meaning |
|---|---|
| `id` | lowercase id used by scenes (`caesar`, `wright_flyer`) |
| `kind` | `person`, `animal`, `creature`, `object`, `machine`, `vehicle`, `building` or `other` |
| `name` | who / what it is ("Julius Caesar", "the Wright Flyer") |
| `noun` | 1-3 plain words for what it is (`man`, `woman`, `biplane`, `steam engine`, `dog`); used to find it in pictures |
| `design` | the fixed look that never changes, in detail: age, build, face, hair, skin / shape, colours, materials, marks. No clothes here for people |
| `look` | the default clothes / state shown in the portrait (optional) |
| `looks` | other named looks scenes can ask for: clothes, damage, paint, season (optional) |
| `reference_image` | your own portrait in `refs/` to use instead of a generated one (optional) |

Scenes list the subjects that are in the picture with `"subjects": ["caesar"]`, or
`[{ "id": "caesar", "look": "captive" }]` for another look. The `image_prompt` then just says what happens
("the man laughing on the pirate deck at dusk"); the studio adds the identity.

What the studio does automatically:
1. Draws 3 reference portraits per subject (one subject, whole, plain parchment background) and keeps the clearest.
   One more portrait per named look a scene uses, made from the main portrait.
2. Draws every scene that lists subjects in two passes: first from text (the scene with the subject's design
   written out) for the composition, then again from that picture with the portraits as FLUX 3 reference
   images, which locks the face / design. Up to 3 subjects per scene. Thumbnails can list `subjects` too.
3. Checks each picture against its portrait: people by the head (a scene where no face is visible is not
   checked), everything else by the whole subject. If it does not match, it redraws with a new seed, up to 3
   tries; the best one is kept and flagged in `report.md`.
4. Saves the portraits in `work/subjects/`, a `subjects_sheet.jpg` next to the video, and a copy in
   `refs/subjects/<project>/`. To reuse a subject in a later video, set its `reference_image` to
   `subjects/<project>/<id>.png`.

Use subjects for anything seen in 2+ scenes. Crowds, landscapes and one-off people stay plain text pictures.
Subjects are for `still` and `wan` scenes; dialogue scenes are the mascots. A subject scene takes ~3 min
instead of ~1 min. Changing a subject's `design` or looks redraws its portrait and all its scenes.

## Character

`{ "name": "<character>", "pose": "talk_right", "side": "left", "expression": "happy", "beats": [{"t": 2.5, "expression": "smug"}] }`

- `name`: a character in your library (`compose.characters_dir`; none yet)
- `pose`: `talk_front`, `talk_left`, `talk_right` (any expression), or one-expression action poses:
  `point_left`, `point_right`, `shrug`, `walk_right`, `sit` (neutral); `idea_finger_up`, `hands_on_hips`, `bow`
  (happy); `arms_crossed` (smug); `cheer` (laughing); `cower` (scared); `run_right` (shocked); `read_scroll` (thinking)
- `expression`: neutral, happy, laughing, smug, angry, sad, scared, shocked, thinking
- `beats`: expression changes at `t` seconds; `side`: left, center, right; `height` (0.8 of frame); `flip`
- The character whose voice tag opens the narration talks; others listen. Facing each other: left one
  `talk_right`, right one `talk_left`.

## Overlay

`{ "kind": "date", "text": "75 BC", "start": 0.4, "end": 3.0, "position": "top_left" }`
- `kind`: `title`, `date`, `label`, `stat`, `headline`, `subscribe`; `position`: `top_left`, `top_right`, `top`, `bottom`, `center`
- `label` (stat and headline only): the caption under the number / the masthead line
- `end` omitted = until the scene ends. Captions need ~1 s on screen to be read.

Kind `subscribe`: `{ "kind": "subscribe", "start": 0.5 }` draws the animated LIKE + SUBSCRIBE badge for
5 seconds (the scene is held until it finishes); no text needed. Use it once, in the scene where the narrator (or a character)
asks viewers to like and subscribe, after a payoff in the second half.

Kind `stat`: `{ "kind": "stat", "text": "90°F", "label": "IN THE SHADE", "start": 0.5 }` a big number
card that counts up to its value (times like 3:28:53 just pop). Centred unless `position` is given.

Kind `headline`: `{ "kind": "headline", "text": "Lorz Rode Eleven Miles In A Car", "label": "St. Louis - August 30, 1904", "start": 0.5 }`
a torn newspaper clipping that slams onto the shot. `label` is the masthead line: a place and date, or a real
paper's name only for a headline that paper really printed.

## Map scenes

```json
{ "id": "12", "type": "map", "narration": "[nar|temperature:0.7] ...",
  "map": { "bbox": [11.0, 34.5, 29.5, 43.5],
           "places": [{ "name": "Rome", "lon": 12.5, "lat": 41.9 }, { "name": "Pharmacusa", "lon": 27.4, "lat": 37.3 }],
           "route": [[12.5, 41.9], [15.6, 38.2], [19.5, 37.0], [23.0, 36.3], [27.4, 37.3]],
           "regions": [{ "name": "Mare Nostrum", "lon": 18.0, "lat": 35.2 }] } }
```
A parchment atlas drawn in code (coastlines, rivers, lakes; never modern borders). The camera eases from a wider
view (`start_bbox`, default 1.7x) to `bbox` = [lon_min, lat_min, lon_max, lat_max]; the route draws itself on
(`route_start`/`route_end` seconds, default 25%-80% of the scene); pins pop in when the route reaches them
(or at `at` seconds); `regions` are atlas names without pins. Give the route waypoints along the real path
(around coasts, not across land). Best for regional and continental journeys; city streets are not drawn.

## Sound effects and music

`"sfx": [{ "name": "cannon", "at": 1.2, "volume_db": -8 }]` plays a sound `at` seconds into the scene.
Built-ins (synthesised, no copyright): `cannon`, `pistol`, `whoosh`, `thud`, `ding`, `tick`. Your own files go in
`assets/sfx/` with a `<name>.license.txt` (`source:`, `license:`, `attribution:`); safe sources are Freesound
filtered to CC0 and the YouTube Audio Library. Music works the same way in `assets/music/` (YouTube Audio
Library tracks are the safest). Unlicensed files are rejected; credits go into youtube.md automatically.

Captions: every render also writes `captions.srt` next to the video (upload it in YouTube Studio as subtitles).
Nothing is burned into the picture.

## Chapters

Add `"chapter": "Short Name"` to the first scene of each section. `youtube.md` gets real timestamps
(0:00 first). YouTube needs at least 3 chapters, each at least 10 s. Editing chapter names never re-renders.

## meta (YouTube packaging, top level)

| field | meaning |
|---|---|
| `angle` | the one-sentence curiosity gap the video pays off |
| `hook` | what the first 5 seconds show and say |
| `titles` | 1-5 title options (3 recommended, 40-60 characters) |
| `description` | YouTube description; chapters are appended automatically in `youtube.md` |
| `tags` | up to 30 search terms |
| `thumbnails` | exactly 3: `{ "description", "concept", "image_prompt", "text", "text_position"?, "character"?, "subjects"?, "seed"? }` |
| `retention_notes` | the open loops / re-hooks / payoffs plan (copied to `youtube.md`) |

Thumbnail `character`: `{ "name": "<character>", "pose": "talk_front", "expression": "shocked", "side": "right" }`
(the mascot is cut out big with a white outline; the text goes on the other side). `text`: 1-4 big words or "".
Without `meta`, the studio still makes 3 simple thumbnails from scene pictures.

## Checks

Errors (script rejected): invalid JSON, unknown/missing fields, missing `type`, unknown voice, narration
without a voice tag, dialogue voice not on screen, two characters on one side, unknown character, pose or
expression, `meta` without exactly 3 thumbnails or without a title, a `map` scene without its `map` block
(or a bad bbox / route), an unknown sound effect, a music or sfx file without its `.license.txt`, an unknown
subject or look, a subject listed twice in a scene, subjects in a dialogue or map scene or together with
`base_image`, a subject `reference_image` that is not in `refs/`. Warnings (renders anyway): a subject that no
scene uses or only one scene uses, a short subject design, a scene whose image prompt names a subject without
listing it in `subjects`, digits in
narration, very short or long scenes, captions starting after the scene ends, three push_ins in a row, prompts
asking for text, too many Wan scenes, empty `style`, no `meta`, long titles, wordy thumbnail text, too few or too
short chapters, opening on the mascots or a slow hook, a missing / early / repeated like & subscribe moment, map pins outside the final view, a straight two-point
route, a long stat or headline, a headline masthead that looks like a newspaper name, a sound effect timed
after the scene ends.

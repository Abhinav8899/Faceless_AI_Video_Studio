# Script format (YesterVerse Studio 1.0)

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

## Scene

| field | for | meaning |
|---|---|---|
| `id` | all, required | unique, e.g. "01" |
| `type` | all, required | `still`, `dialogue` or `wan` |
| `narration` | all, required | starts with a voice tag: `[nar|temperature:0.7]`, `[inventor|temperature:0.8]`, `[apprentice|temperature:0.9]`. The scene lasts as long as the narration |
| `image_prompt` | all | what is in the picture (dialogue: the empty background; people are removed automatically) |
| `camera` | still, dialogue | `push_in` (default), `pull_out`, `pan_left`, `pan_right`, `static` |
| `characters` | dialogue, required | 1-2 mascots, see below |
| `motion_prompt` | wan, required | one simple action, ideally ending "the camera stays still" |
| `overlays` | any | captions, see below |
| `seed` | any | override the picture seed for this scene (use to get a different picture) |
| `base_image` + `edit_prompt` (+ `reference_image`) | still, wan | edit an existing picture in `refs/` instead of generating from text |
| `tail_silence` | any | extra pause after this scene's narration |

## Character

`{ "name": "inventor", "pose": "talk_right", "side": "left", "expression": "happy", "beats": [{"t": 2.5, "expression": "smug"}] }`

- `name`: `inventor`, `apprentice`
- `pose`: `talk_front`, `talk_left`, `talk_right` (any expression), or one-expression action poses:
  `point_left`, `point_right`, `shrug`, `walk_right`, `sit` (neutral); `idea_finger_up`, `hands_on_hips`, `bow`
  (happy); `arms_crossed` (smug); `cheer` (laughing); `cower` (scared); `run_right` (shocked); `read_scroll` (thinking)
- `expression`: neutral, happy, laughing, smug, angry, sad, scared, shocked, thinking
- `beats`: expression changes at `t` seconds; `side`: left, center, right; `height` (0.8 of frame); `flip`
- The character whose voice tag opens the narration talks; others listen. Facing each other: left one
  `talk_right`, right one `talk_left`.

## Overlay

`{ "kind": "date", "text": "75 BC", "start": 0.4, "end": 3.0, "position": "top_left" }`
- `kind`: `title`, `date`, `label`; `position`: `top_left`, `top_right`, `top`, `bottom`, `center`
- `end` omitted = until the scene ends. Captions need ~1 s on screen to be read.

Kind `subscribe`: `{ "kind": "subscribe", "start": 0.5 }` draws the animated LIKE + SUBSCRIBE badge for
5 seconds (the scene is held until it finishes); no text needed. Use it once, in the scene where the inventor
asks viewers to like and subscribe, after a payoff in the second half.

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
| `thumbnails` | exactly 3: `{ "description", "concept", "image_prompt", "text", "text_position"?, "character"?, "seed"? }` |
| `retention_notes` | the open loops / re-hooks / payoffs plan (copied to `youtube.md`) |

Thumbnail `character`: `{ "name": "apprentice", "pose": "talk_front", "expression": "shocked", "side": "right" }`
(the mascot is cut out big with a white outline; the text goes on the other side). `text`: 1-4 big words or "".
Without `meta`, the studio still makes 3 simple thumbnails from scene pictures.

## Checks

Errors (script rejected): invalid JSON, unknown/missing fields, missing `type`, unknown voice, narration
without a voice tag, dialogue voice not on screen, two characters on one side, unknown character, pose or
expression, `meta` without exactly 3 thumbnails or without a title. Warnings (renders anyway): digits in
narration, very short or long scenes, captions starting after the scene ends, three push_ins in a row, prompts
asking for text, too many Wan scenes, empty `style`, no `meta`, long titles, wordy thumbnail text, too few or too
short chapters, opening on the mascots or a slow hook, a missing / early / repeated like & subscribe moment.

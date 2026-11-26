# Instruction prompt for the web AI

How to use:
1. Fill in the CHANNEL PROFILE block below once (channel name, niche, tone, characters). Keep it for every video.
2. Copy everything between the two lines into ChatGPT, Claude, Gemini or similar, and replace the last line with
   your topic (or "suggest 5 video ideas first") and target length.
3. Save the JSON it returns as `<anything>.json` and drop it in the studio's `inbox/` folder. If the studio rejects
   it, paste the contents of the `.errors.txt` file back into the same chat and ask the AI to fix the script.

---------------------------------------------------------------------------------------------------------------

You are the head writer, director and YouTube strategist of the faceless YouTube channel described in the
CHANNEL PROFILE. Your job is a video people click, watch to the end, and subscribe after: a compelling idea, an
attention-grabbing hook, engaging titles, three thumbnail concepts, a tight opening sequence, a storytelling
structure built for retention, a call to action, and the complete scene-by-scene script.

The output is ONE JSON object in the exact format at the end. An automated studio turns it into the finished
video and thumbnails with no human in between, so the format must be exact. Reply with the JSON only, in a
single ```json code block. (If I ask for ideas first, answer with ideas in plain text and wait.)

## CHANNEL PROFILE (filled in by me)

- Channel name: <CHANNEL NAME>
- Niche and what a typical video is about: <e.g. "unsolved science mysteries", "how everyday things are made">
- Tone and pace: <e.g. "calm and curious", "fast, witty, high-energy">
- Narrator persona: <e.g. "a warm, slightly sarcastic documentary host">
- Recurring characters for dialogue scenes: <NONE YET> (when the studio has a character library, list each
  one here: name, personality, role. Until then, use NO dialogue scenes and NO thumbnail `character`.)
- Fixed dialogue background (only with characters): <one image_prompt describing their set, used word for word>

The art style is fixed by the studio. Never describe art style; describe only WHAT is in each picture.

## 1. Idea and packaging (decide this FIRST, the script serves it)

- Angle: one sentence that creates a curiosity gap: a surprising, specific, true claim the video pays off.
  Prefer stories with a twist, a conflict, an absurd detail, or a "this actually happened" factor. Avoid topics
  with no tension.
- Titles: 3 options, 40-60 characters, specific and curiosity-driven (numbers, stakes, contradiction, a name
  people know). Honest: the video must deliver what the title promises. No ALL CAPS titles, no emoji.
- Thumbnails: 3 genuinely different concepts (e.g. the single most dramatic image of the story; a contrast or
  "wait, what?" image; a close-up of the key person or object). Each one:
  - `description`: what the thumbnail shows, in plain words (I use this to choose)
  - `concept`: why it gets the click (emotion, curiosity, contrast)
  - `image_prompt`: the picture only: one bold subject, close-up, strong emotion, simple background. NO text in it.
  - `text`: 1-4 big words that ADD to the title instead of repeating it, or "".
  - optional `character` (only if the profile lists characters): one cut out big on one side, e.g.
    `{ "name": "<character>", "pose": "talk_front", "expression": "shocked", "side": "right" }`
- Description: 2-3 short paragraphs for YouTube: the hook in the first line, what the viewer will learn, and a
  subscribe line. Tags: 8-15 relevant search terms.

## 2. Opening sequence (the first 30 seconds decide everything)

1. Hook, scene 1, under 8 seconds: the most surprising moment or a bold claim, told out of order. No greetings,
   no "in this video". The very first words must create a question in the viewer's head.
2. Promise (1-2 scenes) with the `title` overlay: name what the viewer will find out and plant an open loop:
   "...and by the end, you'll see why that was a terrible idea." (With characters: one dialogue scene.)
3. Bridge (1 scene): set the scene (time, place or context), with a `date` or `label` overlay if it helps.

## 3. Story structure built for retention

- Sections in a clear order, each ending on a line that pulls into the next.
- Re-hook every 30-45 seconds: a new question, a twist, "but that's not the strangest part".
- Open loops: raise a question early and pay it off later. Pay off EVERY loop you open.
- Pattern interrupts: vary shot types and camera; a stat card, map or headline after big moments (with
  characters: a short reaction scene every 5-7 scenes).
- The turn: the reversal, the price, the irony. Short punchy lines.
- No filler, no recap, no "let's dive in". Every scene must move the story.
- Close fast after the climax: pay off the hook and land the lesson in one line.

## 4. Call to action: like & subscribe (exactly once, about 5 seconds)

- One scene right AFTER the biggest payoff, in the second half of the video (never in the first quarter, never
  at the very end). Narrator `still` scene, or a dialogue scene if the channel has characters.
- The narration asks for it in a way tied to the story, 14-18 words.
- Add this overlay to that scene: `{ "kind": "subscribe", "start": 0.5 }` (the studio draws an animated
  LIKE + SUBSCRIBE badge for 5 seconds).

## 5. Writing the narration

- One idea per scene, 6-22 words (about 3-8 seconds of speech). Never more than two sentences.
- Write for the ear: short words, concrete nouns, the key word at the end of the sentence.
- ALL numbers and dates as words: "nineteen sixty", "eleven kilometres", "thirty-eight days". No digits, no
  abbreviations in narration (digits are fine in overlays and titles).
- Every narration starts with exactly one voice tag: `[nar|temperature:0.7]` for the narrator (characters:
  `[<name>|temperature:0.8]`, only names the studio has voices for).
- Facts only. If sources disagree, say "about" or "reportedly". No invented quotes.

## 6. Scene types

- `"still"` (MOST scenes): one illustration with a slow camera move. Needs `image_prompt` and `camera`.
- `"dialogue"` (only if the profile lists characters): characters on their fixed background. Needs
  `image_prompt` (the profile's fixed background, word for word) and `characters`; the voice tag must be one of
  the characters in the scene.
- `"map"`: a map drawn in code: the camera eases in, a route draws itself, pins pop in. Use 1-2 per video for
  journeys and "where is this" moments. No image_prompt; needs a `map` block:
  `{ "bbox": [lon_min, lat_min, lon_max, lat_max], "places": [{ "name": "Guam", "lon": 144.8, "lat": 13.4 }],
  "route": [[lon, lat], ...], "regions": [{ "name": "Philippine Sea", "lon": 133.0, "lat": 18.0 }] }`. Use real
  coordinates; route waypoints follow the real path (around coasts, not over land); max 5 places. Works for
  regions and continents, not city streets.
- `"wan"`: AI-animated video, slow and can smear. Only 1-3 moments where motion IS the story. Needs
  `image_prompt` and `motion_prompt` (one simple action, "the camera stays still").

## 7. Image prompts and style

- `style` (top level): the setting ONLY (period, place, environment), one short sentence with no objects or
  people in it: everything in `style` appears in EVERY picture.
- Each image_prompt describes ONE picture: who or what, doing what, where, one concrete object in focus.
  15-40 words. Setting-correct details (clothes, tools, lighting). Never ask for writing, signs or labels.
- People who are NOT subjects (section 7b): by appearance and clothing ("an old fisherman in a yellow raincoat").
  For maps use a `map` scene (section 6), never an image prompt.
- Vary the shots: wide establishing views, medium group shots, close-ups of a face or object.

## 7b. Subjects: keep the main people and things identical in every scene

The studio draws each subject once as a reference portrait and builds every scene that lists it from that
portrait, so the face (or the shape and colours of a thing) never changes. Use it for:
- the main person or people of the story (anyone seen in 2+ scenes), and
- any thing the story keeps returning to: a vehicle, an invention, a machine, a tool, an animal, a building.

Top level `"subjects"` (2-6 per video), each:
`{ "id": "piccard", "kind": "person", "name": "Jacques Piccard", "noun": "man", "design": "...", "look": "...", "looks": { "diving": "..." } }`
- `kind`: `person`, `animal`, `creature`, `object`, `machine`, `vehicle`, `building` or `other`
- `noun`: 1-3 plain words for what it is (`man`, `woman`, `girl`, `submarine`, `robot`, `telescope`, `dog`)
- `design`: the FIXED look, 25-60 words, very specific. People: age, build, face shape, nose, eyes, hair,
  facial hair, skin, scars (NO clothes here). Things: overall shape, size, materials, colours, distinctive
  parts. Nothing written on it.
- `look`: default clothes / state (people: full outfit; things: e.g. "hatch closed", optional)
- `looks`: other named looks the story needs ("diving", "old_age", "winter_gear", "damaged", "rebuilt")
- In a scene: `"subjects": ["piccard"]`, or `[{ "id": "piccard", "look": "diving" }]`; max 3 per scene;
  `still` and `wan` scenes only. The `image_prompt` then refers to it plainly ("the man", "the submarine") and
  describes the action, place, angle and other people. Do NOT repeat the design in the prompt.
- Every scene that shows a subject MUST list it, otherwise it is drawn from text and looks different.
- A subject's age jump of more than ~15 years: a separate subject (`piccard_young`, `piccard_old`).
- Thumbnails can list `"subjects"` too, so the thumbnail matches the video.

## 8. Camera (still and dialogue)

`"push_in"`, `"pull_out"`, `"pan_left"`, `"pan_right"`, `"static"`. Never the same move three scenes in a row.
`pan_*` for journeys and wide views, `pull_out` to reveal or end a section, `static` when a caption must be read
and for dialogue, `push_in` toward a dramatic face or detail.

## 9. Characters (dialogue scenes, 1 or 2; only if the profile lists characters)

`{ "name": "<character>", "pose": "talk_right", "side": "left", "expression": "happy", "beats": [{ "t": 2.5, "expression": "smug" }] }`
- `side`: `left`, `center`, `right` (two characters on different sides)
- `pose`: facing each other: LEFT one `talk_right`, RIGHT one `talk_left`; alone in the centre `talk_front`.
  Other poses only if the profile lists them.
- `expression`: neutral, happy, laughing, smug, angry, sad, scared, shocked, thinking (only these)
- `beats`: expression changes at `t` seconds (keep `t` within the scene, about words / 2.6 seconds).

## 10. Overlays and chapters

- Overlay: `{ "kind": "date", "text": "JANUARY 1960", "start": 0.4, "position": "top_left" }`. Kinds: `title`
  (once, in the intro), `date` (time jumps), `label` (places, numbers, groups), `subscribe` (once, see section 4).
  Text max 30 characters, CAPITALS. Positions: `top_left`, `top_right`, `top`, `bottom`, `center`. Max 2 per scene.
- `stat`: one striking number that counts up: `{ "kind": "stat", "text": "10,916 M", "label": "BELOW THE SURFACE", "start": 0.5 }`.
  1-3 per video, on the most surprising figures; the number is also said in the narration (in words).
- `headline`: a newspaper clipping slams in: `{ "kind": "headline", "text": "Bathyscaphe Reaches Ocean Floor",
  "label": "Guam - January 23, 1960", "start": 0.5 }`. 0-2 per video, for a scandal or turning point; 3-7 words;
  `label` is a place and date (never invent a newspaper name or quote a headline that was not printed).
- Sound effects (sparingly, 2-6 per video, on story beats): `"sfx": [{ "name": "whoosh", "at": 1.2 }]` on a scene.
  Built-ins: `cannon`, `pistol`, `whoosh` (time jumps, transitions), `thud`, `ding` (a reveal), `tick`.
  Headlines get a thud and maps a whoosh automatically. Do not add music unless asked. Only effects that fit
  the setting.
- Chapters: add `"chapter": "Name"` to the first scene of each section: 3-6 chapters, the first on scene 1, each
  at least 10 seconds long. Chapter names are short and intriguing.

## Exact format

(The topic of this example only shows the format; write about MY topic.)

```json
{
  "project": "short-lowercase-id-with-dashes",
  "style": "The setting in one short sentence.",
  "defaults": { "seed": 7500, "tail_silence": 0.3, "scene_gap": 0.15 },
  "meta": {
    "angle": "One-sentence curiosity gap the video pays off.",
    "hook": "What the first 5 seconds show and say.",
    "titles": ["Title option one", "Title option two", "Title option three"],
    "description": "Hook line.\n\nWhat the viewer learns.\n\nSubscribe line.",
    "tags": ["tag one", "tag two"],
    "thumbnails": [
      { "description": "...", "concept": "...", "image_prompt": "...", "text": "BIG WORDS" },
      { "description": "...", "concept": "...", "image_prompt": "...", "text": "", "subjects": ["trieste"] },
      { "description": "...", "concept": "...", "image_prompt": "...", "text": "TWO WORDS", "text_position": "top" }
    ],
    "retention_notes": ["open loop planted in scene 02, paid off in scene 15", "re-hook at scene 09: ..."]
  },
  "subjects": [
    { "id": "piccard", "kind": "person", "name": "Jacques Piccard", "noun": "man",
      "design": "a tall lean Swiss man of thirty-seven, long narrow face, high forehead, receding dark hair combed back, thin straight nose, round wire glasses, pale skin",
      "look": "grey wool sweater over a white shirt, dark trousers",
      "looks": { "diving": "thick knitted jumper, wool cap, headphones around the neck" } },
    { "id": "trieste", "kind": "vehicle", "name": "the Trieste", "noun": "submarine",
      "design": "a bathyscaphe: a long grey cigar-shaped float with a small conning tower on top and a single round steel crew sphere hanging underneath, two portholes, rust streaks" }
  ],
  "scenes": [
    { "id": "01", "type": "still", "chapter": "Seven Miles Down",
      "narration": "[nar|temperature:0.7] Two men sealed themselves inside a steel ball and dropped seven miles into the dark.",
      "image_prompt": "The submarine sinking into black water, a faint beam of light from its porthole, tiny glowing particles drifting past",
      "subjects": ["trieste"],
      "camera": "push_in" },
    { "id": "02", "type": "still",
      "narration": "[nar|temperature:0.7] Nobody knew if the window would hold, and by the end, you'll see how close it came.",
      "image_prompt": "Close-up of the man peering through a small thick porthole, lit by a dim cabin lamp",
      "subjects": [{ "id": "piccard", "look": "diving" }],
      "camera": "push_in",
      "overlays": [{ "kind": "title", "text": "THE DEEPEST DIVE", "start": 0.4, "end": 3.0, "position": "top" }] },
    { "id": "03", "type": "map",
      "narration": "[nar|temperature:0.7] The target was the Challenger Deep, south of Guam in the Pacific.",
      "map": { "bbox": [138.0, 8.0, 150.0, 16.5],
               "places": [{ "name": "Guam", "lon": 144.8, "lat": 13.4 }, { "name": "Challenger Deep", "lon": 142.2, "lat": 11.35 }],
               "route": [[144.8, 13.4], [143.9, 12.6], [142.2, 11.35]],
               "regions": [{ "name": "Pacific Ocean", "lon": 146.5, "lat": 9.5 }] } },
    { "id": "04", "type": "wan",
      "narration": "[nar|temperature:0.7] On the morning of the dive, the sea was rough enough to smash equipment.",
      "image_prompt": "The submarine rolling in heavy grey waves beside a small navy tug, spray flying over the deck",
      "subjects": ["trieste"],
      "motion_prompt": "waves rise and fall around the submarine, the camera stays still" },
    { "id": "05", "type": "still",
      "narration": "[nar|temperature:0.7] Nearly five hours later, they touched the bottom, ten thousand nine hundred metres down.",
      "image_prompt": "The submarine resting on a pale silty sea floor in total darkness, its lamp lighting a small cloud of silt",
      "subjects": ["trieste"],
      "camera": "pull_out",
      "overlays": [{ "kind": "stat", "text": "10,916 M", "label": "BELOW THE SURFACE", "start": 0.6 }],
      "sfx": [{ "name": "thud", "at": 0.4, "volume_db": -10 }] }
  ]
}
```

Optional per thumbnail: `"text_position": "left" | "right" | "top" | "bottom"`, `"seed": 1234`, `"subjects": [...]`,
`"character"` (only with characters).
Optional per subject: `"looks"`, `"reference_image"` (only if I give you a file name).
Optional elsewhere (section 10): overlay kind `"headline"` with `"label"`; map `"start_bbox"`, `"route_start"`,
`"route_end"`, a place's `"at"`; an sfx `"volume_db"`.
Rules: scene ids unique ("01", "02", ...); every scene has `id`, `type`, `narration`; exactly 3 thumbnails;
no fields other than the ones shown; no comments; no trailing commas.

Length guide: 1 minute is about 150 words and 14-16 scenes; 3 minutes about 450 words and 40-45 scenes;
5 minutes about 750 words and 70 scenes.

Before answering, silently check: the hook lands in the first 8 seconds with no greeting; 3 titles and 3 truly
different thumbnails; every open loop is paid off; a re-hook every 30-45 seconds; exactly one like & subscribe
scene with the `subscribe` overlay, after a payoff in the second half; every narration has a voice tag and no
digits; no dialogue scenes or thumbnail characters unless the profile lists characters (and then every dialogue
voice is on screen); every main person or recurring thing is a subject with a detailed `design`, and EVERY
still / wan scene that shows it lists it in `subjects`; no three identical camera moves in a row; at most 3 wan
scenes; 1-2 map scenes when the story travels; 1-3 stat cards on the most surprising numbers; sound effects only
on real story beats and fitting the setting; 3-6 chapters.

MY VIDEO: <topic>, about <N> minutes.

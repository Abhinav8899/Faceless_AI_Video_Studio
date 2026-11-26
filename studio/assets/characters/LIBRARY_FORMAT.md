# Character library format (for dialogue scenes and thumbnail characters)

The studio ships with no characters. A library is a folder such as `assets/characters/main/`; point
`compose.characters_dir` in `config.yaml` at it. Until it exists, scripts must not use dialogue scenes or a
thumbnail `character` (the checker rejects them).

## Layout (per character)

    <character>/
      model.png                         canonical design, the identity anchor for everything else
      turnaround/<view>.png             front, three_quarter_left/right, profile_left/right, back
      poses/<pose>/<expression>_<mouth>.png
                                        mouth = closed | open; open is made FROM closed, so swapping
                                        closed/open moves only the mouth (talking flap)
      cutouts/<same tree>.png           transparent, cropped, 24 px margin; used for compositing

Dialogue poses (talk_front, talk_left, talk_right) need every expression:
neutral, happy, laughing, smug, angry, sad, scared, shocked, thinking.
Each expression is edited FROM that pose's neutral image, so the body stays put when switching.

Optional action poses have one fitting expression (closed + open), e.g. point_right, point_left,
idea_finger_up, arms_crossed, hands_on_hips, shrug, cheer, cower, walk_right, run_right, sit, bow, read_scroll.
Avoid poses where a hand touches the face: the image model mangles them.

`index.json` lists every image with its pose/expression/mouth, cutout path and feet anchor (bottom-centre of the
character in cutout pixels), for the compositor to place characters on the ground. `manifest.json` records the
parent, seed and prompt of every generated image. About 95 images per character.

## Tools

`_tools/` has the generators: `mascot_design.py` (design candidates from `DESIGNS`),
`charlib.py` (model, turnaround, poses and expressions from a style file), `charlib_post.py` (cut-outs,
index.json, sheets), `qa_char.py` and `review_sheet.py`. They need a style file describing the art style
(`_tools/style.txt`: your art style, plain flat light grey background, no texture). Put your characters in
`CHARACTERS` in `charlib.py`, then run, inside the studio folder with ComfyUI running:

    .venv/bin/python assets/characters/_tools/mascot_design.py            # pick a candidate, save it as main/<name>/model.png
    cd assets/characters && ../../.venv/bin/python _tools/charlib.py . main --style-file _tools/style.txt
    python _tools/charlib_post.py main                                      # needs rembg

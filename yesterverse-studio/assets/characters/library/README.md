# Character library (empty)

Generated character images live here and are not committed. Dialogue scenes and mascot thumbnails need it;
`still` and `wan` scenes work without it.

Layout expected by `pipeline/compose.py`:

    library/
      index.json
      <character>/poses/<pose>/<expression>_closed.png   mouth closed
      <character>/poses/<pose>/<expression>_open.png     mouth open (talking)
      <character>/cutouts/...                            same tree, transparent PNGs

Build one with the tools in `../_tools/` (needs ComfyUI running with the FLUX.2 Klein edit workflow):

    # 1. a base image of each character in ~/ComfyUI/characters/ (see CHARACTERS in charlib.py)
    .venv/bin/python assets/characters/_tools/charlib.py assets/characters library \
        --style-file assets/characters/_tools/style_parchment.txt --chars <name>
    # 2. cutouts + index.json (needs: pip install -e ".[characters]")
    .venv/bin/python assets/characters/_tools/charlib_post.py assets/characters/library
    # 3. review sheet / automatic checks
    .venv/bin/python assets/characters/_tools/review_sheet.py assets/characters/library/<name> review_<name>.jpg
    .venv/bin/python assets/characters/_tools/qa_char.py assets/characters/library/<name> qa_<name>

Each character also needs a voice in `~/ComfyUI/models/voices/<name>.wav` (+ `<name>.txt` transcript) and its
name in `tts.voices` in `config.yaml`.

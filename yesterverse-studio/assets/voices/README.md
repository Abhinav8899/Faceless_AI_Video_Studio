# Voices (none included)

Renders read voices from `ComfyUI/models/voices/<name>.wav` + `<name>.txt` (exact transcript). Every name in
`config.yaml` → `tts.voices` needs one (default: `nar`, `inventor`, `apprentice`).

Create them with `studio voice` (see the README), for example:

    studio voice nar "Rich, confident adult male narrator, 30s to 40s, warm documentary tone, measured pace"

Keep a copy of the voices you use in this folder (it is git-ignored, so they never get published):

    cp ~/ComfyUI/models/voices/<name>.{wav,txt} assets/voices/          # back up
    cp assets/voices/*.{wav,txt} ~/ComfyUI/models/voices/               # restore
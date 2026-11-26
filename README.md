# Studio2

Drop a script in, get a finished faceless YouTube video out: narration, illustrated scenes with slow camera
moves, maps, captions, sound, three thumbnails and the YouTube description, rendered on your own machine with
ComfyUI. Scripts are written by a web AI (ChatGPT, Claude, Gemini) from `PROMPT_FOR_WEB_AI.md`.

Everything runs on ONE Linux machine with an NVIDIA GPU: the studio, ComfyUI and the models.

## Requirements

- Linux with systemd (tested on Ubuntu 22.04), an NVIDIA GPU with 16 GB VRAM (tested on an RTX A4000), 32 GB RAM,
  about 60 GB free disk for models and a few GB per video
- Python 3.10+, `ffmpeg` and `ffprobe` on the PATH
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) installed with its own venv in `ComfyUI/venv`
  (default location `~/ComfyUI`), and these custom nodes in `ComfyUI/custom_nodes/`:
  - [TTS-Audio-Suite](https://github.com/diodiogod/TTS-Audio-Suite) (Qwen3-TTS voices, voice design, audio save)
  - [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) (Wan 2.2 GGUF models)
- Models (put each file in the ComfyUI folder shown; file names must match `models:` in `config.yaml`):

| file | ComfyUI folder | used for |
|---|---|---|
| `flux3-image-klein-int8-convrot.safetensors` | `models/diffusion_models` | pictures, edits, thumbnails (FLUX 3 Image Klein) |
| `qwen3vl_4b_int8_convrot.safetensors` | `models/text_encoders` | FLUX 3 text encoder |
| `flux2-vae.safetensors` | `models/vae` | FLUX VAE |
| `Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf`, `Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf` | `models/unet` | `wan` motion scenes |
| `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors`, `..._low_noise.safetensors` | `models/loras` | 4-step Wan |
| `umt5_xxl_fp8_e4m3fn_scaled.safetensors` | `models/text_encoders` | Wan text encoder |
| `Wan2.1_VAE.safetensors` | `models/vae` | Wan VAE |

  Qwen3-TTS is downloaded by TTS-Audio-Suite on first use. Other quantisations work if you change the file
  names in `config.yaml`.
- Optional, for the automatic likeness check of subjects: `torch` and `transformers` in ComfyUI's venv (it
  runs there on the CPU). The two small models (OWLv2 base, DINOv2 base, about 1 GB) are downloaded from
  Hugging Face on first use. Without them the check is skipped with a note and renders carry on.

FLUX 3 Image Klein is used under the FLUX Kommunity License (free for commercial use under US$5M yearly
revenue at the time of writing; check the current terms).

## Install

Clone into a folder named `studio2` (the folder name is also the command and service name):

    git clone <this repo> studio2
    cd studio2
    python3 -m venv .venv
    .venv/bin/pip install -e . pytest
    .venv/bin/python -m pytest -q tests          # should all pass
    bin/install-services ~/ComfyUI               # your ComfyUI folder
    ln -s "$PWD/bin/studio2" ~/.local/bin/studio2   # optional: run `studio2` from anywhere

`bin/install-services` adds two systemd user services: `studio-comfyui.service` (ComfyUI) and
`studio2.service` (the inbox watcher). Neither starts at boot; `studio2 start` / `studio2 stop` control them.
To keep renders running after you log out: `sudo loginctl enable-linger $USER`.

Check everything with: `.venv/bin/python -m pipeline.cli doctor` (models, voices, workflows, ComfyUI, disk).

Without systemd: start ComfyUI yourself, then run `studio2 watch` in a terminal (or `studio2 make` per script).

## Set up your channel (assets start empty)

| what | how |
|---|---|
| narrator voice `nar` (required) | `studio2 voice nar "<description>"` |
| more voices (characters) | `studio2 voice <name> "<description>"`, then add the name to `tts.voices` in `config.yaml` |
| art style | `style.house` in `config.yaml` (added to every picture prompt; a neutral placeholder until you change it) |
| characters for dialogue scenes | a library in `assets/characters/<set>/` (see `assets/characters/LIBRARY_FORMAT.md`), then set `compose.characters_dir` |
| music, sound effects | your licensed files in `assets/music/`, `assets/sfx/`, each with a `.license.txt` |
| channel profile for the web AI | the CHANNEL PROFILE block in `PROMPT_FOR_WEB_AI.md` |

A voice is designed from one sentence (age, gender, pitch, tone, pace, accent) and saved in
`ComfyUI/models/voices/` (named `<tts.voice_prefix><name>`). Listen to the preview it prints
(`output/_voices/`) and run again with `--force` until you like it:

    studio2 voice nar "Calm, warm male documentary narrator in his forties, low pitch, clear American accent, unhurried"

Drawn by code in a parchment storybook look (change the code to restyle): the overlay cards (date, label, title,
stat, headline), the LIKE + SUBSCRIBE badge and the map scenes. Fonts: `assets/fonts/` (Cinzel for overlays,
Bangers for thumbnail text; replace with files of the same names). `compose.finish_strength` adds a paper
grain over composed shots (0 = off). The likeness thresholds in `subjects:` were calibrated on that storybook
style; check the likeness column of your first `report.md` and adjust if good scenes are being redrawn.

## Folders

    studio2/
      inbox/        drop scripts here (.json, or .txt containing the JSON)
      processing/   the script being rendered right now
      output/<project>/   everything for one video:
                    <project>.mp4, captions.srt, thumbnail_1-3.jpg, thumbnails_compare.jpg, youtube.md,
                    report.md, contact sheets, script.json
                    work/     working files (voices, images, clips; cached, so re-submitting only redoes changed scenes)
                    logs/     one log per render     scripts/  every version of the script you submitted
      failed/       rejected or failed scripts + <name>.errors.txt explaining what to fix
      logs/         studio.log (service), comfyui.log, status.json
      refs/subjects/<project>/   reference portraits of each video's subjects, for reuse
      examples/example_script.json   a short working script
      PROMPT_FOR_WEB_AI.md   paste into a web AI to write scripts
      SCRIPT_FORMAT.md       the format, field by field
      OVERSEER.md            how an AI assistant can supervise a render step by step
      assets/       characters/ (your library + tools), fonts/, voices/, geo/ (map data), sfx/, music/
      workflows/api/  the ComfyUI graphs the studio sends
      systemd/      service templates used by bin/install-services
      pipeline/     the code;  config.yaml  settings (paths, models, resolution, voices, house style)

## Making a video

1. `studio2 start` (starts ComfyUI and the inbox service, waits until ready).
2. Write the script with a web AI using `PROMPT_FOR_WEB_AI.md` (it also writes titles, description, tags,
   chapters, the like & subscribe moment and 3 thumbnail concepts). Save it as `my_video.json`.
3. Check it (optional, instant): `studio2 check my_video.json`
4. Put it in the inbox: `cp my_video.json inbox/`
5. Wait. Progress: `studio2 status` or `tail -f logs/studio.log`.
6. Collect from `output/<project>/`:
   - `<project>.mp4`: the video (1080p, loudness normalised for YouTube, no burned-in subtitles)
   - `captions.srt`: subtitles timed to the narration (upload in YouTube Studio if you want exact captions)
   - `thumbnail_1.jpg` ... `thumbnail_3.jpg` (1280x720) and `thumbnails_compare.jpg`: pick one
   - `youtube.md`: title options, description with chapter timestamps, tags, credit lines for music/effects
   - `report.md`: automatic checks (resolution, audio, loudness, black frames, silences, length, a likeness
     score per subject scene) and `final_contact_sheet.jpg` (one frame per scene)
   - `subjects_sheet.jpg`: the reference portraits of the video's subjects (if the script has any)
7. `studio2 stop` when you are done (frees the GPU).

If the script has a mistake it lands in `failed/` with an `.errors.txt` in plain English and nothing is
rendered. Paste that text into the web AI chat, get the fixed script, drop it in again.
Changing a script and dropping it in again (same `project`) re-renders only the scenes that changed.
A render interrupted by a crash or reboot resumes on the next start.

## What a video can contain

- `still` scenes (most of the video): one illustration with a slow camera move
- `dialogue` scenes: your characters talking (mouths follow the voice); needs a character library
- `wan` scenes: a few seconds of AI animation, for the 1-3 moments where motion is the story
- `map` scenes: a map drawn in code; the camera eases in, a route draws itself, pins pop in
- overlays: `title`, `date`, `label`, `stat` (a number that counts up), `headline` (a newspaper clipping that
  slams in), `subscribe` (the like & subscribe badge)
- sound: built-in effects (`cannon`, `pistol`, `whoosh`, `thud`, `ding`, `tick`, synthesised so there is no
  copyright), your own licensed effects, and an optional licensed music bed that ducks under the voice
- subjects: the main people and things (a person, an animal, a tool, a machine, a vehicle, a building) look
  the same in every scene, see below

## Consistent subjects

Without help, every picture is drawn from text alone, so a person's face (or a machine's shape) drifts from
scene to scene. A script's `subjects` block fixes that automatically:

1. Each subject gets a reference portrait: 3 are drawn and the clearest is kept. Each extra named look (other
   clothes, damaged, older...) gets its own portrait made from the main one.
2. Every scene listing the subject is drawn in two passes: from text first (new pose, angle and background),
   then again from that picture with the portrait(s) as FLUX 3 reference images, which pulls the face or design
   onto the portrait's (up to 3 subjects per scene; thumbnails too).
3. A likeness check compares every such picture with its portrait (OWLv2 finds the subject by its `noun`,
   DINOv2 compares it; people by the head so clothes can change, things as a whole). Below the threshold the
   scene is redrawn with a new seed, up to 3 tries; the best is kept and flagged in `report.md`. Tiny subjects
   and people whose face is not visible are not checked. Small drift can pass, so still glance at the sheets.
4. Portraits: `output/<project>/work/subjects/`, `subjects_sheet.jpg`, and a copy in `refs/subjects/<project>/`
   (set a subject's `reference_image` to reuse one in a later video, or to your own picture).

Settings (`config.yaml`, `subjects:`): `portrait_candidates`, `compose_from_text`, `denoise`,
`threshold_person`, `threshold_thing`, `max_attempts`, `min_area`, `check` (false turns the check off).

## Music and sound effects (licensed files only)

Put files in `assets/music/` or `assets/sfx/` and name them in the script (`"music": "track.mp3"`, or
`"sfx": [{ "name": "explosion.wav", "at": 1.0 }]`). Every file needs a licence note beside it, `<name>.license.txt`:

    source: YouTube Audio Library
    license: YouTube Audio Library, attribution not required
    attribution:

A script that names a file without its note is rejected. A non-empty `attribution:` line is added to the
description in `youtube.md`. Safe sources: the YouTube Audio Library, Freesound.org filtered to CC0,
Incompetech (CC BY, needs the credit line).

## Render time (RTX A4000)

About 75 s per still scene, ~3 min per subject scene, ~3.5 min of portraits per subject, ~20 s per dialogue
scene, ~1 min per map scene, ~2 min per Wan scene. `studio2 check` prints an estimate for a script.

## Commands

    studio2 start                              start ComfyUI + the inbox service
    studio2 stop                               stop both (a render in progress resumes on the next start)
    studio2 status                             service state, queue, latest outputs
    studio2 check  script.json                 check only: errors, warnings, length/render-time estimate
    studio2 make   script.json [--until images] render in the foreground, stopping after a stage
                   [--only-scene 07 --force]   redo one scene
    studio2 review <project>                   rebuild the review sheets and report
    studio2 voice  <name> "<description>"      design a new voice
    studio2 thumbnail "<description>" [--text "BIG WORDS"] [--project NAME] [--variants 3]
                                               extra thumbnails (the script's 3 are kept)

A long foreground `studio2 make` stops if its terminal closes; for long renders use the inbox, or
`nohup studio2 make script.json > make.log 2>&1 &`. Foreground `make` and the service share a GPU lock
(`~/.cache/studio/gpu.lock`), so only one render runs at a time, also across several studio folders on the
same machine. If ComfyUI is already running (started by hand), `studio2 start` uses it and `studio2 stop`
leaves it alone.

## Several channels on one machine

Clone the repo again into another folder name (e.g. `studio3`), run `bin/install-services` there (and link
its launcher under the folder's name: `ln -s "$PWD/bin/studio2" ~/.local/bin/studio3`), and give it
its own `paths.comfy_subfolder` and `tts.voice_prefix` in its `config.yaml` so the two never share ComfyUI
files or voices. They share ComfyUI, the models and the GPU queue; `stop` leaves ComfyUI running while
another studio's service is still on.

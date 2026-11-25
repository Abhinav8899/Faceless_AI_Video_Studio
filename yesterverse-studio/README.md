# YesterVerse Studio

Drop a script in, get a finished, YouTube-ready video out.

A faceless history-explainer pipeline that runs on one GPU machine and drives a local ComfyUI:
Qwen3-TTS voices, FLUX.2 Klein images and edits, optional Wan2.2 image-to-video, then code-composited
shots (camera moves, jitter-free character rig, overlays, parchment finish), loudness-normalised render,
3 thumbnails, YouTube metadata and an automatic quality report.

This repository has the code only. Models, voices, the character library and all outputs are **not**
included; see [Requirements](#requirements).

    inbox/        drop scripts here (.json, or .txt containing the JSON)
    processing/   the script being rendered right now
    output/<project>/   everything for one video:
                  <project>.mp4, thumbnail_1-3.jpg, youtube.md, report.md, contact sheets, script.json
                  work/      working files: voices, images, clips (cached: re-submitting only redoes changed scenes)
                  logs/      one log per render        scripts/   every version of the script you submitted
                  thumbnails_extra/   from `studio thumbnail --project`
    failed/       rejected or failed scripts + <name>.errors.txt explaining what to fix
    logs/         studio.log (service), comfyui.log, status.json
    examples/example_script.json      a complete example video script
    PROMPT_FOR_WEB_AI.md              paste into a web AI chat to write scripts
    SCRIPT_FORMAT.md                  the script format, field by field
    OVERSEER.md                       supervising a render step by step (e.g. by an AI assistant)
    assets/       fonts, character library (empty) + the tools to build one, voices/ (empty)
    pipeline/     the code;  config.yaml  settings (models, resolution, voices, house style)
    deploy/       systemd unit templates;  scripts/install.sh  one-time setup

## Requirements

- Linux with an NVIDIA GPU (developed on 16 GB VRAM, 32 GB RAM), Python 3.10+, `ffmpeg`.
- [ComfyUI](https://github.com/comfyanonymous/ComfyUI) (default location `~/ComfyUI`) with these custom nodes:
  - [TTS-Audio-Suite](https://github.com/diodiogod/TTS-Audio-Suite) (Qwen3-TTS engine)
  - [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) (Wan2.2 GGUF loader)
- Models (file names are set in `config.yaml` → `models`):

  | folder in `ComfyUI/models/` | file |
  |---|---|
  | `diffusion_models` | `flux-2-klein-4b.safetensors` |
  | `text_encoders` | `qwen_3_4b.safetensors`, `umt5_xxl_fp8_e4m3fn_scaled.safetensors` |
  | `vae` | `flux2-vae.safetensors`, `Wan2.1_VAE.safetensors` |
  | `unet` | `Wan2.2-I2V-A14B-HighNoise-Q5_K_M.gguf`, `Wan2.2-I2V-A14B-LowNoise-Q5_K_M.gguf` |
  | `loras` | `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors`, `..._low_noise.safetensors` |

  Wan is only needed for `wan` scenes; `still` and `dialogue` scenes use FLUX only.
- Voices: for every name in `config.yaml` → `tts.voices` (default `nar`, `inventor`, `apprentice`), a reference
  clip `ComfyUI/models/voices/<name>.wav` and its transcript `<name>.txt`. None are included: create them with
  `studio voice` (see [Creating voices](#creating-voices)) or bring your own recordings.
- Character library (optional, for dialogue scenes and mascot thumbnails): see
  [`assets/characters/library/README.md`](assets/characters/library/README.md).

Check everything with `.venv/bin/python -m pipeline doctor` after installing.

## Install

    git clone <this repo> yesterverse-studio
    cd yesterverse-studio
    scripts/install.sh            # or: scripts/install.sh /path/to/ComfyUI

This creates `.venv`, links the `studio` command into `~/.local/bin`, and writes two systemd *user* units
(`studio.service`, `studio-comfyui.service`). Nothing starts at boot.

## Making a video

0. Start the studio (starts ComfyUI too, waits until everything is ready):

       studio start

   When you are finished: `studio stop` (stops the service and ComfyUI, frees the GPU).
1. Write the script with a web AI using `PROMPT_FOR_WEB_AI.md` (it also writes titles, description, tags,
   chapters, the like & subscribe moment and 3 thumbnail concepts).
2. Copy it into `inbox/`, e.g. from another computer:

       scp my_video.json <user>@<gpu-host>:<repo>/inbox/

3. Wait. Progress: `studio status` or `tail -f logs/studio.log`.
4. Collect from `output/<project>/`:
   - `<project>.mp4`: the video (1080p, loudness normalised to -16 LUFS)
   - `thumbnail_1.jpg` … `thumbnail_3.jpg` (1280x720) and `thumbnails_compare.jpg`: pick one
   - `youtube.md`: title options, description with chapter timestamps, tags, thumbnail notes
   - `report.md`: automatic checks (resolution, audio, loudness, black frames, silences, length) and
     `final_contact_sheet.jpg` (one frame per scene)

If the script has a mistake it lands in `failed/` with an `.errors.txt` in plain English and nothing is
rendered. Paste that text into the web AI chat, get the fixed script, drop it in again.

Changing a script and dropping it in again (same `project`) re-renders only the scenes that changed.
A render interrupted by a crash or reboot resumes automatically.

## Commands

    studio start                              start ComfyUI + the inbox service
    studio stop                               stop both (a render in progress resumes on the next start)
    studio status                             service state, queue, latest outputs
    studio check  script.json                 check only: errors, warnings, length/render-time estimate
    studio make   script.json [--until images] render in the foreground, stopping after a stage
                  [--only-scene 07 --force]   redo one scene
    studio review <project>                   rebuild the review sheets and report
    studio thumbnail "<description>" ...      extra thumbnails (see below)
    studio voice <name> "<description>"       design a new character voice (see below)

If ComfyUI is already running elsewhere, `studio start` uses it and `studio stop` leaves it alone.

### Extra thumbnails from a description

The 3 thumbnails from the script are always made. For more options:

    studio thumbnail "young Caesar laughing at three confused pirates in a ship cabin" \
        --text "50 TALENTS?!" --character apprentice:shocked:right --project caesar-and-the-pirates

- `--text`: 1-4 big words (optional); `--position left|right|top|bottom` (default: opposite the mascot)
- `--character name[:expression[:side[:pose]]]`: a character from the library; leave it out for no mascot
- `--project`: saves to `output/<project>/thumbnails_extra/<time>/` and uses that video's era style
  (without it: `output/_thumbnails/<time>/`; give the era with `--style "Ancient Rome, 75 BC"`)
- `--variants 1-6` (default 3), `--seed N` to reproduce one exactly (seeds are in the compare sheet)

### Creating voices

Design a voice from a description (Qwen3-TTS VoiceDesign, workflow `workflows/api/voice_design.api.json`):

    studio voice nar "Rich, confident adult male narrator, 30s to 40s, warm documentary tone, measured pace"
    studio voice inventor "Elderly eccentric male inventor, raspy, excitable, fast talker, slight crackle"
    studio voice apprentice "Young adult, bright medium pitch, curious and cheeky, energetic friendly pace"

- Saves `ComfyUI/models/voices/<name>.wav` + `<name>.txt`, the files every line is cloned from, and a copy to
  `output/_voices/<name>_seed<N>.wav` to listen to (about 35 s per voice once the model is loaded).
- Describe age, gender, pitch, tone, pace and accent. `--text "..."` changes what the clip says,
  `--seed N` reproduces a voice, `--force` replaces an existing one (otherwise existing names are refused).
- Add the name to `tts.voices` in `config.yaml`, then use it in scripts: `[name|temperature:0.8] Hello!`
- Keep a backup in `assets/voices/` (git-ignored); see its README.
- Needs the TTS-Audio-Suite custom node; the VoiceDesign model downloads on first use.

## Development

    .venv/bin/python -m pytest -q

Render time on an RTX A4000: about 25 s per still/dialogue scene and ~2 min per Wan scene.

Fonts in `assets/fonts` are from Google Fonts under the SIL Open Font License (see `LICENSES.txt`).

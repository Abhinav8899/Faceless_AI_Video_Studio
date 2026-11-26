# Studio2

Drop a script in, get a finished video out. A second, independent instance of the YesterVerse studio,
for another channel.

## Set up this studio first (your channel's own look and voices)

Studio2 is a second, independent copy of the YesterVerse studio for another channel. It shares ComfyUI, the
models and the GPU with `~/youtube/studio` (only one render runs at a time across both; the other waits), but
nothing else: its own inbox, outputs, settings, voices and characters. Its assets start EMPTY:

| what | where | status |
|---|---|---|
| narrator voice `nar` (required) | `studio2 voice nar "<description>"` | to design |
| other voices (characters) | `studio2 voice <name> "<description>"`, then add the name to `tts.voices` in `config.yaml` | optional |
| art style | `style.house` in `config.yaml` (added to every picture prompt) | placeholder, replace it |
| characters for dialogue scenes | `assets/characters/<set>/` (format: `assets/characters/LIBRARY_FORMAT.md`), then set `compose.characters_dir` | none (no dialogue scenes until then) |
| music, sound effects | `assets/music/`, `assets/sfx/` with a `.license.txt` beside each file | empty (built-in effects still work) |
| channel profile for the web AI | the CHANNEL PROFILE block in `PROMPT_FOR_WEB_AI.md` | to fill in |

Voices: studio2 saves its voices as `s2_<name>` in `ComfyUI/models/voices` (`tts.voice_prefix: s2_`), so its
`nar` never overwrites YesterVerse's `nar`. In scripts you still write `[nar|temperature:0.7]`.
Describe a voice in one sentence (age, gender, pitch, tone, pace, accent), listen to the preview it prints
(`output/_voices/`), and run it again with `--force` until you like it. Example:

    studio2 voice nar "Calm, warm male documentary narrator in his forties, low pitch, clear American accent, unhurried"

Still in the YesterVerse look because it is drawn by code, not by asset files: the overlay cards (date, label,
title, stat, headline), the LIKE + SUBSCRIBE badge, the map scenes (parchment atlas) and the fonts (Cinzel for
overlays, Bangers for thumbnail text, in `assets/fonts/`, same file names to replace). The paper grain over
composed shots is off here (`compose.finish_strength: 0`). Ask Claude to restyle these once you have chosen the
channel's look.

The likeness thresholds in `subjects:` were calibrated on the parchment style; check the likeness column in the
first video's `report.md` and adjust if good scenes are being redrawn.


    ~/youtube/studio2/
      inbox/        drop scripts here (.json, or .txt containing the JSON)
      processing/   the script being rendered right now
      output/<project>/   everything for one video:
                    <project>.mp4, captions.srt, thumbnail_1-3.jpg, thumbnails_compare.jpg, youtube.md,
                    report.md, contact sheets, script.json
                    work/     working files (voices, images, clips; cached, so re-submitting only redoes changed scenes)
                    logs/     one log per render     scripts/  every version of the script you submitted
                    thumbnails_extra/  from `studio2 thumbnail --project`
      failed/       rejected or failed scripts + <name>.errors.txt explaining what to fix
      logs/         studio.log (service), comfyui.log, status.json
      examples/example_script.json      the short example from PROMPT_FOR_WEB_AI.md (stills, subjects, a map, Wan, a stat)
                  refs/subjects/<project>/          reference portraits of each video's subjects, for reuse
      PROMPT_FOR_WEB_AI.md              paste into ChatGPT/Claude/Gemini to write scripts
      SCRIPT_FORMAT.md                  the format, field by field
      OVERSEER.md                       how Claude supervises a render step by step
      assets/       characters/ (your library + character tools), fonts/, voices/ (studio copy),
                    geo/ (map data), sfx/ and music/ (your licensed sound files)
      workflows/api/  the ComfyUI graphs the studio sends (retired/ = old FLUX.2 graphs, unused)
      pipeline/     the code;  config.yaml  settings (models, resolution, voices, house style)

## Making a video

0. Start the studio (starts ComfyUI too, waits until everything is ready):

       studio2 start

   When you are finished: `studio2 stop` (stops the service and ComfyUI, frees the GPU). Nothing starts at boot.
1. Write the script with a web AI using `PROMPT_FOR_WEB_AI.md` (it also writes titles, description, tags,
   chapters, the like & subscribe moment and 3 thumbnail concepts).
2. Copy it to the inbox, from your PC (asks for the password):

       scp my_video.json abhinav@172.16.24.132:~/youtube/studio2/inbox/

   or drag it into `inbox/` in VS Code Remote-SSH.
3. Wait. Progress: `~/youtube/studio2/bin/studio2 status` or `tail -f ~/youtube/studio2/logs/studio.log`.
4. Collect from `output/<project>/`:
   - `<project>.mp4`: the video (1080p, loudness normalised for YouTube, no burned-in subtitles)
   - `captions.srt`: subtitles timed to the narration; upload it in YouTube Studio (Subtitles) if you want
     exact captions instead of YouTube's automatic ones
   - `thumbnail_1.jpg`, `thumbnail_2.jpg`, `thumbnail_3.jpg` (1280x720) and `thumbnails_compare.jpg` with each
     option's description: pick one
   - `youtube.md`: title options, description with chapter timestamps, tags, thumbnail notes, and any credit
     lines your music or sound effects require
   - `report.md`: automatic checks (resolution, audio, loudness, black frames, silences, length, a likeness
     score per subject scene) and `final_contact_sheet.jpg` (one frame per scene)
   - `subjects_sheet.jpg`: the reference portraits of the video's subjects (if the script has any)

If the script has a mistake it lands in `failed/` with an `.errors.txt` in plain English, and nothing is
rendered. Paste that text into the web AI chat, get the fixed script, drop it in again.

Changing a script and dropping it in again (same `project`) re-renders only the scenes that changed.
A render interrupted by a crash or reboot resumes automatically.

## What a video can contain

- `still` scenes (most of the video): one illustration with a slow camera move
- `dialogue` scenes: your characters talking (mouths follow the voice); needs a character library first
- `wan` scenes: a few seconds of AI animation, for the 1-3 moments where motion is the story
- `map` scenes: a map drawn in code; the camera eases in, a route draws itself, pins pop in
- overlays: `title`, `date`, `label`, `stat` (a number that counts up), `headline` (a newspaper clipping that
  slams in), `subscribe` (the like & subscribe badge)
- sound: built-in effects (`cannon`, `pistol`, `whoosh`, `thud`, `ding`, `tick`, synthesised so there is no
  copyright), your own licensed effects, and an optional licensed music bed that ducks under the voice

- subjects: the main people and things (a person, an animal, a tool, a machine, a ship, a building) look the
  same in every scene, see below

`SCRIPT_FORMAT.md` has every field; `examples/example_script.json` is a short working example.

## Consistent subjects

Without help, every picture is drawn from text alone, so a person's face (or a machine's shape) drifts from
scene to scene. A script's `subjects` block fixes that automatically, no human needed:

1. Each subject gets a reference portrait: 3 are drawn (one subject, whole, plain background) and the
   clearest is kept. Each extra named look (other clothes, damaged, older paint...) gets its own portrait made
   from the main one, so the face / design carries over.
2. Every scene listing the subject is drawn in two passes: from text first (the scene with the design written
   out, so the pose, angle and background are new), then from that picture again with the portrait(s) as FLUX 3
   reference images, which pulls the face / design onto the portrait's (up to 3 subjects per scene; thumbnails
   too). Drawing from the portrait alone copies its pose and plain background, hence the text pass.
3. A likeness check compares every such picture with its portrait: OWLv2 finds the subject by its `noun`,
   DINOv2 compares it patch by patch (people by the head, so clothes can change; things as a whole). Below the
   threshold the scene is redrawn with a new seed, up to 3 tries; the best one is kept and listed as a warning
   in `report.md`. The check runs on the CPU in ComfyUI's Python and takes about 1-6 s per picture. Tiny
   subjects in wide shots, and people whose face is not visible, are not checked. It catches a wrong or
   missing subject reliably; small drift (a slightly different nose) can pass, so still glance at the sheets.
4. Portraits: `output/<project>/work/subjects/`, `subjects_sheet.jpg`, and a copy in
   `refs/subjects/<project>/` (set a subject's `reference_image` to one of these to reuse it in a later video,
   or to your own picture).

Settings (`config.yaml`, `subjects:`): `portrait_candidates`, `compose_from_text`, `denoise`,
`threshold_person` (0.72), `threshold_thing` (0.65), `max_attempts`, `min_area`, `check` (false turns the
check off). The check models (~1 GB) are in `~/.cache/huggingface`; if they are
missing the check is skipped with a note in the log and the render carries on.

## Music and sound effects (licensed files only)

Put files in `assets/music/` or `assets/sfx/` and name them in the script (`"music": "track.mp3"`, or
`"sfx": [{ "name": "explosion.wav", "at": 1.0 }]`). Every file needs a licence note beside it, `<name>.license.txt`:

    source: YouTube Audio Library
    license: YouTube Audio Library, attribution not required
    attribution:

A script that names a file without its note is rejected. A non-empty `attribution:` line is added to the
description in `youtube.md`. Safe sources: the YouTube Audio Library (music and sound effects; not claimed by
Content ID), Freesound.org filtered to CC0, Incompetech (CC BY, needs the credit line). Avoid generic
"copyright free" sites: their tracks are sometimes claimed by third parties.

## Models

| job | model (ComfyUI) | time |
|---|---|---|
| pictures, picture edits, thumbnails | FLUX 3 Image Klein (distilled, int8) + Qwen3-VL 4B text encoder + FLUX.2 VAE | ~65 s per picture, ~2.5 min per edit |
| motion (`wan` scenes) | Wan 2.2 I2V A14B (Q5 GGUF) + Lightx2v 4-step LoRAs | ~2 min per scene |
| voices | Qwen3-TTS 1.7B (voice clone; VoiceDesign for `studio2 voice`) | a few seconds per scene |
| likeness check (subjects) | OWLv2 base (finds the subject) + DINOv2 base (compares it), CPU | 1-6 s per picture |

Render time: about 75 s per still scene (picture + compose), ~3 min per subject scene (text pass, portrait
pass, check, an occasional redraw), ~3.5 min per subject for its portraits, ~20 s per dialogue scene (the
background is reused), ~1 min per map scene, ~2 min per Wan scene. `studio2 check` prints an estimate.

FLUX 3 is used under the FLUX Kommunity License: free for commercial use while yearly revenue is under
US$5M; review pictures before publishing and mark the video as altered/synthetic content in YouTube Studio
where it applies.

## Commands (`studio2` works from any folder on the GPU box)

    studio2 start                              start ComfyUI + the inbox service
    studio2 stop                               stop both (a render in progress resumes on the next start)
    studio2 status                             service state, queue, latest outputs
    studio2 check  script.json                 check only: errors, warnings, length/render-time estimate
    studio2 make   script.json [--until images] render in the foreground, stopping after a stage
                  [--only-scene 07 --force]   redo one scene
    studio2 review <project>                   rebuild the review sheets and report
    studio2 voice  <name> "<description>"      design a new character voice

A long `studio2 make` over SSH stops if the connection drops; for long renders use the inbox, or
`nohup studio2 make script.json > make.log 2>&1 &`.

If ComfyUI is already running (started by hand), `studio2 start` uses it and `studio2 stop` leaves it alone.
ComfyUI's log: `logs/comfyui.log`. The service keeps running after you close SSH.

To change thumbnails only: edit `meta.thumbnails` in the script and drop it in again; the video is cached,
only the changed thumbnails are regenerated.

## Extra thumbnails from a description

The 3 thumbnails from the script are always made. If one fails or you want more options:

    studio2 thumbnail "the submarine sinking into black water, one porthole glowing" \
        --text "7 MILES DOWN" --project <project>

- `--text`: 1-4 big words (optional); `--position left|right|top|bottom` (default: opposite the mascot)
- `--character name[:expression[:side[:pose]]]`: a character from your library, any expression, `left`/`right`
  (default `talk_front`); leave it out for no character
- `--project`: saves to `output/<project>/thumbnails_extra/<time>/` and uses that video's era style
  (without it: `output/_thumbnails/<time>/`; give the era with `--style "the setting"`)
- `--variants 1-6` (default 3, ~65 s each), `--seed N` to reproduce one exactly (the seeds are in the compare sheet)

It writes `thumbnail_1.jpg` ... and `thumbnails_compare.jpg`. The script's own thumbnails are never touched.

# Overseen render (Claude supervises)

Use this when the user hands Claude a finished script instead of dropping it in the inbox. Claude runs the
render in stages from the user's PC over SSH and inspects the results before spending GPU time on the next
stage. Everything below runs on the GPU box from `~/youtube/studio2`.

Run every stage detached so a dropped SSH connection cannot kill it, then poll the log:

    nohup bin/studio2 make scripts/<name>.json --until images > /tmp/<name>_images.log 2>&1 &

FLUX 3 takes about 65 s per picture, so the images stage of a 10-minute video runs for about 2.5 hours.

1. Check: `bin/studio2 check scripts/<name>.json`. Fix errors in the script (keep the user's wording; only
   fix format, tags, digits, poses, and so on), then report any warnings that change the content.
   Also check era: no sound effect or headline the period could not have (no cannon before ~1350, no pistol
   before ~1500, no newspaper headline before ~1700), and every music/sfx file has its `.license.txt`.
2. Voices: `--until audio`. Read `output/<project>/work/review/report.md`: scene lengths should be 2-10 s;
   listen-check suspicious ones (very short or very long for their word count) by pulling
   `output/<project>/work/audio/scene_<id>.flac`.
   Subjects: every main person and recurring thing should be in the `subjects` block with a detailed `design`,
   and every still/wan scene that shows it should list it (the checker warns when a prompt names a subject the
   scene does not list).
3. Pictures: `--until images`. First look at `output/<project>/work/review/subjects_sheet.jpg` (run
   `bin/studio2 review <project>` if it is not there yet): the portraits decide every subject scene. A bad portrait
   (wrong era, extra limbs, two subjects, cut off): change the subject's `design`/`look` or set `defaults.seed`
   differently, and run again; its portrait and all its scenes are redrawn. Then read `report.md` for scenes
   flagged "may not match its portrait" and look at those first. Then look at `output/<project>/work/review/images_sheet.jpg` (or build your own
   sheets of 6 for a closer look). Reject and regenerate any image with: wrong era (modern objects, wrong
   clothes), garbled text, extra limbs or mangled hands/faces, people in a dialogue background, missing
   clothing, or a picture that does not match its narration (e.g. "runners" drawn in suits).
   Map scenes appear as their final frame: check the route follows the real path (not over land), the pins
   are in the right places and labels do not cover each other.
   Regenerate one scene: edit its `image_prompt` in the script (keep the seed so the voice stays identical),
   then run the stage again; the studio redoes only the changed scenes. To force one scene:
   `--until images --only-scene <id> --force`.
4. Motion: `--until compose`, then look at `output/<project>/work/review/frames_sheet.jpg`. Wan scenes: check
   for smearing or morphing; redo with a simpler `motion_prompt` or switch the scene to `"still"`.
   Dialogue: mascots on-model, standing on the floor, not cut off, eyes steady while talking. Overlays:
   readable, not covering the subject (stat and headline cards default to the centre; give a `position` if
   they hide the action). Map scenes: the camera move and the route timing match the narration.
5. Final: `bin/studio2 make <script>` (renders, makes thumbnails and publishes to `output/<project>/`). Read
   `report.md`: every check must pass. Look at `final_contact_sheet.jpg` and `thumbnails_compare.jpg`, and
   check `captions.srt` exists. If the script has sound effects or music, listen to those moments: effects
   audible but not louder than the voice, music well under the narration.
6. Report to the user: the output path, length, what was regenerated and why, and anything left to judge by
   ear or eye (voice delivery, jokes landing, sound levels).

Foreground `make` and the inbox service share a GPU lock, so they never render at the same time.

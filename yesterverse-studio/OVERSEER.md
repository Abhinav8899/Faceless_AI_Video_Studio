# Overseen render (Claude supervises)

Use this when the user hands Claude a finished script instead of dropping it in the inbox. Claude runs the
render in stages from the user's PC over SSH and inspects the results before spending GPU time on the next
stage. Everything below runs on the GPU box from the repo folder.

1. Check: `bin/studio check scripts/<name>.json`. Fix errors in the script (keep the user's wording; only
   fix format, tags, digits, poses, and so on), then report any warnings that change the content.
2. Voices: `bin/studio make <script> --until audio`. Read `output/<project>/work/review/report.md`: scene lengths
   should be 2-10 s; listen-check suspicious ones (very short or very long for their word count) by pulling
   `output/<project>/work/audio/scene_<id>.flac`.
3. Pictures: `bin/studio make <script> --until images`, then look at `output/<project>/work/review/images_sheet.jpg`.
   Reject and regenerate any image with: wrong era (modern objects, wrong clothes), garbled text, extra limbs
   or mangled hands/faces, people in a dialogue background, or a picture that does not match its narration.
   Regenerate one scene: edit its `image_prompt` (or add `"seed": <new number>` to the scene), then
   `bin/studio make <script> --until images --only-scene <id> --force`.
4. Motion: `bin/studio make <script> --until compose`, then look at `output/<project>/work/review/frames_sheet.jpg` (two frames per
   moving shot). Wan scenes: check for smearing or morphing; redo with a simpler `motion_prompt` or switch the
   scene to `"still"`. Dialogue: mascots on-model, standing on the floor, not cut off.
5. Final: `bin/studio make <script>` (renders and publishes to `output/<project>/`). Read `report.md`: every
   check must pass. Look at `final_contact_sheet.jpg`.
6. Report to the user: the output path, length, what was regenerated and why, and anything left to judge by
   ear or eye (voice delivery, jokes landing).

Foreground `make` and the inbox service share a GPU lock, so they never render at the same time.

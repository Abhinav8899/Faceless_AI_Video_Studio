# Music (licensed tracks only)

Put a track here and name it in a script: `"music": "calm-strings.mp3"` (optional `"music_volume_db": -24`).
It loops under the whole video, fades in and out, and ducks automatically while someone is speaking.

Every track needs a licence note beside it with the same name: `calm-strings.license.txt`

    source: YouTube Audio Library
    url: https://studio.youtube.com/...      (optional: where you downloaded it)
    license: YouTube Audio Library, attribution not required
    attribution:                             (the credit line if the licence asks for one)

Without the note the script is rejected. A non-empty `attribution:` line is added to the YouTube
description in `youtube.md` automatically.

Safe sources: YouTube Audio Library (Studio -> Audio Library, filter "Attribution not required"; not claimed
by Content ID), Incompetech / Kevin MacLeod (CC BY: fill in `attribution:`), Free Music Archive tracks marked
CC0 or CC BY. Avoid generic "copyright free" sites and anything you cannot point to a licence for.
Formats: mp3, wav, flac, ogg, m4a.

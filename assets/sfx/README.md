# Sound effects

Scenes can play sounds: `"sfx": [{ "name": "cannon", "at": 1.2, "volume_db": -8 }]` (`at` = seconds into the scene).

Built-in (synthesised by `pipeline/sfx.py`, no recordings, so no copyright; generated into `_builtin/`):
`cannon`, `pistol`, `whoosh`, `thud`, `ding`, `tick`. Headline cards get a `thud` and map scenes a `whoosh`
automatically (`"auto_sfx": false` at the top of a script turns that off).

Your own recordings: put the file here (`explosion.wav`) and use its name (`"name": "explosion"` or
`"explosion.wav"`). Every file needs a licence note beside it: `explosion.license.txt`

    source: freesound.org/s/12345 (user name)
    license: CC0
    attribution:                             (the credit line if the licence asks for one)

Without the note the script is rejected; credit lines go into `youtube.md`. Safe sources: Freesound.org
filtered to CC0, the YouTube Audio Library "Sound effects" tab. Keep effects era-correct.

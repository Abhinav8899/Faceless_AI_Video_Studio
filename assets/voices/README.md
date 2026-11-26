# Voices

The renders read voices from `ComfyUI/models/voices/` (file names `<tts.voice_prefix><name>.wav` + `.txt`
transcript + `.reference.txt`). This folder is empty: design your own with

    studio2 voice nar "Calm, warm male documentary narrator in his forties, low pitch, clear American accent, unhurried"
    studio2 voice host "Energetic young woman, bright medium pitch, fast and playful, light British accent"

and add every name except `nar` to `tts.voices` in `config.yaml`. In scripts a voice is used as a tag:
`[nar|temperature:0.7] ...`, `[host|temperature:0.8] ...`.

Keep a backup copy of your finished voices here (the `.wav`, `.txt` and `.reference.txt` files), so the studio
folder holds everything for the channel. Restore after reinstalling ComfyUI with:

    cp assets/voices/*.wav assets/voices/*.txt ~/ComfyUI/models/voices/
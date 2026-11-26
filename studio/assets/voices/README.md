# Channel voices (studio copy)

The renders read voices from `~/ComfyUI/models/voices/`. This folder keeps the studio's own copy of the
three main voices, so the studio folder alone holds everything for the channel.

| file | who | used in scripts as |
|---|---|---|
| `nar.wav` | narrator | `[nar|temperature:0.7] ...` |
| `inventor.wav` | the Inventor (mascot) | `[inventor|temperature:0.8] ...` |
| `apprentice.wav` | the Apprentice (mascot) | `[apprentice|temperature:0.9] ...` |

Each voice is the `.wav` clip plus `.txt` (exact transcript, needed for cloning) and `.reference.txt`.

Restore (e.g. after reinstalling ComfyUI or replacing a voice by mistake):

    cp ~/youtube/studio/assets/voices/*.{wav,txt} ~/ComfyUI/models/voices/

New voices made with `studio voice` go to ComfyUI/models/voices; copy them here too if you keep them.

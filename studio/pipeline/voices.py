"""Design a new character voice from a text description (Qwen3-TTS VoiceDesign via TTS-Audio-Suite).

The workflow (workflows/api/voice_design.api.json) speaks a reference paragraph in the described voice and
saves it with "Save Character Voice" as ComfyUI/models/voices/<name>.wav + <name>.txt, which is exactly
what the render's TTS stage clones from. A copy of the clip is put in output/_voices/ to listen to.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from pipeline.comfy import ComfyClient
from pipeline.config import Config
from pipeline.workflows import Workflow

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")

# 20-35 s of varied, neutral speech: questions, exclamations and numbers give the clone a good range.
DEFAULT_TEXT = (
    "Gather round, because this story is stranger than fiction. Two thousand years ago, a young man was "
    "captured at sea, and instead of begging for his life, he laughed! Can you imagine? Thirty-eight days later, "
    "everything had changed. History is full of moments like this, and today, we are going to explore one of "
    "the wildest."
)


def voice_files(config: Config, name: str) -> list[Path]:
    d, f = config.paths.voices_dir, config.tts.file_name(name)
    return [p for p in (d / f"{f}.wav", d / f"{f}.txt", d / f"{f}.reference.txt") if p.exists()]


def design_voice(config: Config, name: str, description: str, out_dir: Path, text: str = "",
                 seed: int | None = None, overwrite: bool = False) -> dict:
    if not NAME_RE.match(name):
        raise ValueError("voice name must be 2-32 lowercase letters, digits or _, starting with a letter "
                         f"(got '{name}')")
    if len(description.strip()) < 10:
        raise ValueError("describe the voice in a sentence: age, gender, pitch, tone, pace, accent")
    existing = voice_files(config, name)
    if existing and not overwrite:
        raise FileExistsError(f"a voice called '{name}' already exists ({existing[0]}); "
                              "pick another name or add --force to replace it")
    seed = seed if seed is not None else int(time.time() * 1000) % 2**31
    wf = Workflow.load(config.workflows.path(config.paths.workflows_dir, "voice_design"), "voice_design")
    wf.set("UnifiedVoiceDesignerNode", "voice_instruction", description.strip())
    wf.set("UnifiedVoiceDesignerNode", "reference_text", (text or DEFAULT_TEXT).strip())
    wf.set("UnifiedVoiceDesignerNode", "seed", seed)
    wf.set("Qwen3TTSEngineNode", "language", config.tts.language)
    wf.set("SaveCharacterVoiceNode", "character_name", config.tts.file_name(name))
    wf.set("SaveCharacterVoiceNode", "overwrite_character", True)   # the existence check above guards this

    t0 = time.monotonic()
    with ComfyClient(config.comfy) as client:
        entry = client.wait(client.submit(wf.dump()), config.timeouts.tts)
    info = ""
    for out in (entry.get("outputs") or {}).values():
        for value in out.get("text", []) if isinstance(out, dict) else []:
            if "sav" in str(value).lower():
                info = str(value)
    wav = config.paths.voices_dir / f"{config.tts.file_name(name)}.wav"
    if not wav.is_file() or wav.stat().st_mtime < time.time() - (time.monotonic() - t0) - 5:
        raise RuntimeError(f"ComfyUI finished but {wav} was not written. Save node said: {info or '(nothing)'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    preview = out_dir / f"{name}_seed{seed}.wav"
    shutil.copy2(wav, preview)
    return {"name": name, "seed": seed, "wav": wav, "preview": preview, "info": info,
            "seconds": round(time.monotonic() - t0, 1)}

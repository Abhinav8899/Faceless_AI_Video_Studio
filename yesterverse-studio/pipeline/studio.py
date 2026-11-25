"""YesterVerse studio: drop a script in inbox/, get a finished video in output/.

  studio start                                    start ComfyUI + the inbox service (waits until ready)
  studio stop                                     stop the inbox service and the ComfyUI it started
  studio check  <script.json>                     strict check only (nothing rendered)
  studio make   <script.json> [--until STAGE]     render in the foreground (oversight mode)
                [--only-scene ID ...] [--force]
  studio review <project>                         rebuild review sheets + quality report
  studio thumbnail "<description>" [--text "BIG WORDS"] [--character apprentice:shocked:right]
                   [--position left|right|top|bottom] [--project NAME] [--variants 3] [--seed N]
                                                  extra thumbnails from a description (the script's 3 stay)
  studio voice <name> "<description>" [--text "..."] [--seed N] [--force]
                                                  design a new character voice (saved to ComfyUI/models/voices)
  studio status                                   service, queue and current job
  studio watch                                    the inbox service (run by systemd)
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import httpx
from rich.console import Console

from pipeline import runner
from pipeline.checker import check_file
from pipeline.compose import ComposeError, Library
from pipeline.config import PROJECT_ROOT, Config, load_config
from pipeline.qa import review
from pipeline.runpaths import run_dir as run_dir_for
from pipeline.thumbnails import make_thumbnails

STUDIO = PROJECT_ROOT
DIRS = {name: STUDIO / name for name in ("inbox", "processing", "done", "failed", "output", "logs")}
STAGE_ORDER = ["audio", "images", "video", "compose", "render", "thumbnails"]
LOCK = STUDIO / "logs" / ".gpu.lock"
STATUS = STUDIO / "logs" / "status.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _log(msg: str) -> None:
    line = f"[{_now()}] {msg}"
    print(line, flush=True)
    with open(DIRS["logs"] / "studio.log", "a") as fh:
        fh.write(line + "\n")


def _status(**kw) -> None:
    try:
        STATUS.write_text(json.dumps({"updated": _now(), **kw}, indent=1))
    except OSError:
        pass


@contextmanager
def gpu_lock(wait_msg: str = "another render is running, waiting..."):
    """One render at a time, shared by the service and foreground `make`."""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK, "w")
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(wait_msg, flush=True)
            fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def library_or_none(config: Config):
    try:
        return Library(config.compose.characters_dir)
    except ComposeError:
        return None


def comfy_up(config: Config) -> bool:
    try:
        return httpx.get(config.comfy.url.rstrip("/") + "/system_stats", timeout=5).status_code == 200
    except httpx.HTTPError:
        return False


def wait_for_comfy(config: Config, poll: float = 15.0) -> None:
    if comfy_up(config):
        return
    _log(f"ComfyUI is not reachable at {config.comfy.url}; waiting (run: studio start)")
    _status(state="waiting_for_comfyui")
    while not comfy_up(config):
        time.sleep(poll)
    _log("ComfyUI is up")


def invalidate_changed(config: Config, script, console: Console) -> list[str]:
    """If a project was rendered before, clear cached assets of scenes whose definition changed
    (and everything if style/negative/defaults changed), so a re-submitted script never reuses stale pictures."""
    directory = run_dir_for(config, script)
    old_path = directory / "script.json"
    if not old_path.is_file():
        return []
    old = json.loads(old_path.read_text())
    new = json.loads(script.model_dump_json())
    global_changed = any(old.get(k) != new.get(k) for k in ("style", "negative", "defaults"))
    def visual(s: dict) -> dict:                 # chapter names do not change any picture or sound
        return {k: v for k, v in s.items() if k != "chapter"}
    old_scenes = {s["id"]: visual(s) for s in old.get("scenes", [])}
    changed = [s["id"] for s in new["scenes"] if global_changed or old_scenes.get(s["id"]) != visual(s)]
    if changed:
        runner.clean(config, script, only_scenes=changed, console=console)
        manifest = directory / "manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text())
            for sid in changed:
                data.get("scenes", {}).pop(sid, None)
            data.pop("render", None)
            manifest.write_text(json.dumps(data, indent=2, sort_keys=True))
        (directory / "final.mp4").unlink(missing_ok=True)
    elif [s["id"] for s in old.get("scenes", [])] != [s["id"] for s in new["scenes"]]:
        (directory / "final.mp4").unlink(missing_ok=True)       # same scenes, new order
    return changed


def render_script(config: Config, script, console: Console, until: str = "thumbnails",
                  only_scenes: list[str] | None = None, force: bool = False) -> Path:
    stages = STAGE_ORDER[: STAGE_ORDER.index(until) + 1]
    if not only_scenes:
        changed = invalidate_changed(config, script, console)
        if changed:
            console.print(f"script changed since the last render: re-doing scene(s) {', '.join(changed)}")
    for stage in stages:
        _status(state="rendering", project=script.project, stage=stage, started=_now())
        if stage == "thumbnails":
            make_thumbnails(config, script, run_dir_for(config, script), library_or_none(config), log=console.print)
            continue
        if stage == "render" and only_scenes:
            runner.run(config, script, stage="render", only_scenes=None, force=True, console=console)
        else:
            runner.run(config, script, stage=stage, only_scenes=only_scenes, force=force, console=console)
    return run_dir_for(config, script)


def _ts(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02d}"


def youtube_md(script, directory: Path) -> str:
    """Upload sheet: titles, description with real chapter timestamps, tags, thumbnail options."""
    manifest = json.loads((directory / "manifest.json").read_text())
    durations = (manifest.get("render") or {}).get("scenes") or {}
    chapters, t = [], 0.0
    for scene in script.scenes:
        if scene.chapter:
            chapters.append((t, scene.chapter))
        t += durations.get(scene.id, 0.0)
    if chapters and chapters[0][0] > 0:
        chapters.insert(0, (0.0, "Intro"))
    meta = script.meta
    out = [f"# {script.project}", "", f"Length: {_ts(t)}", ""]
    if meta:
        out += ["## Title options", ""] + [f"{i}. {title}" for i, title in enumerate(meta.titles, 1)] + [""]
        if meta.angle:
            out += [f"Angle: {meta.angle}", ""]
        if meta.hook:
            out += [f"Hook: {meta.hook}", ""]
    out += ["## Description (paste into YouTube)", "", meta.description.strip() if meta else ""]
    if len(chapters) >= 3:
        out += ["", "Chapters:"] + [f"{_ts(s)} {name}" for s, name in chapters]
    out += [""]
    if meta and meta.tags:
        out += ["## Tags", "", ", ".join(meta.tags), ""]
    if meta:
        out += ["## Thumbnail options", ""]
        for i, th in enumerate(meta.thumbnails, 1):
            out += [f"**Option {i}** (`thumbnail_{i}.jpg`): {th.description}", f"- Why it works: {th.concept}",
                    f"- Text: {th.text or '(none)'}", ""]
        if meta.retention_notes:
            out += ["## Retention plan", ""] + [f"- {n}" for n in meta.retention_notes] + [""]
    return "\n".join(out)


def publish(config: Config, script, script_path: Path, log_path: Path) -> Path:
    """Copy the deliverables to output/<project>/."""
    directory = run_dir_for(config, script)
    rep = review(directory)
    dest = DIRS["output"] / script.project
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(directory / "final.mp4", dest / f"{script.project}.mp4")
    for p in sorted((directory / "thumbnails").glob("thumbnail*.jpg")):
        shutil.copy2(p, dest / p.name)
    (dest / "youtube.md").write_text(youtube_md(script, directory))
    for name in ("report.md", "report.json", "final_contact_sheet.jpg", "images_sheet.jpg", "frames_sheet.jpg"):
        src = directory / "review" / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    shutil.copy2(script_path, dest / "script.json")
    shutil.copy2(log_path, dest / "render.log")
    return dest


# ------------------------------------------------------------------------- service


def process(config: Config, path: Path) -> None:
    name = path.name
    work = DIRS["processing"] / name
    shutil.move(str(path), work)
    _log(f"picked up {name}")
    report = check_file(work, config, library_or_none(config))
    if not report.ok:
        stem = f"{_stamp()}_{work.stem}"
        shutil.move(str(work), DIRS["failed"] / f"{stem}.json")
        (DIRS["failed"] / f"{stem}.errors.txt").write_text(report.text())
        _log(f"REJECTED {name}: {len(report.errors)} error(s), see failed/{stem}.errors.txt")
        _status(state="idle", last=f"rejected {name}")
        return
    script = report.script
    log_path = DIRS["logs"] / f"{script.project}_{_stamp()}.log"
    with open(log_path, "w") as fh:
        fh.write(report.text() + "\n")
        console = Console(file=fh, width=120, force_terminal=False, highlight=False)
        try:
            wait_for_comfy(config)
            with gpu_lock():
                start = time.monotonic()
                _log(f"rendering {script.project} ({len(script.scenes)} scenes), log: logs/{log_path.name}")
                render_script(config, script, console)
                fh.flush()
                dest = publish(config, script, work, log_path)
                mins = (time.monotonic() - start) / 60
        except Exception as exc:  # noqa: BLE001 - the service must survive any job failure
            fh.write("\n" + traceback.format_exc())
            stem = f"{_stamp()}_{work.stem}"
            shutil.move(str(work), DIRS["failed"] / f"{stem}.json")
            (DIRS["failed"] / f"{stem}.errors.txt").write_text(
                f"Render failed for project '{script.project}':\n  {type(exc).__name__}: {exc}\n\n"
                f"Full log: logs/{log_path.name}\n"
                "Already finished scenes are kept; dropping the script in the inbox again resumes from where it stopped.\n")
            _log(f"FAILED {script.project}: {type(exc).__name__}: {str(exc)[:200]}")
            _status(state="idle", last=f"failed {script.project}")
            return
    shutil.move(str(work), DIRS["done"] / f"{_stamp()}_{name}")
    rep = json.loads((dest / "report.json").read_text())
    verdict = "all checks passed" if rep.get("passed") else "CHECK THE REPORT, some checks failed"
    _log(f"DONE {script.project} in {mins:.1f} min -> output/{script.project}/ ({verdict})")
    _status(state="idle", last=f"done {script.project}")


def watch(config: Config) -> None:
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)
    # a job interrupted by a reboot or crash goes back to the inbox and resumes from its cache
    for leftover in DIRS["processing"].glob("*.json"):
        shutil.move(str(leftover), DIRS["inbox"] / leftover.name)
        _log(f"re-queued interrupted job {leftover.name}")
    _log(f"studio watching {DIRS['inbox']}")
    _status(state="idle")
    while True:
        jobs = sorted((p for p in DIRS["inbox"].iterdir() if p.is_file() and not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime)
        for p in jobs:
            if p.suffix.lower() not in (".json", ".txt"):
                continue
            if time.time() - p.stat().st_mtime < 3:      # still being uploaded
                continue
            process(config, p)
            break
        time.sleep(3)


# ------------------------------------------------------------------------- start / stop

COMFY_UNIT = "studio-comfyui.service"
STUDIO_UNIT = "studio.service"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, env=env)


def _unit_active(unit: str) -> bool:
    return _systemctl("is-active", unit).stdout.strip() == "active"


def start(config: Config, timeout: float = 240) -> int:
    if comfy_up(config):
        owner = "started by the studio" if _unit_active(COMFY_UNIT) else "already running outside the studio (e.g. tmux), using it"
        print(f"ComfyUI: up ({owner})")
    else:
        print("ComfyUI: starting... (log: logs/comfyui.log)")
        r = _systemctl("start", COMFY_UNIT)
        if r.returncode:
            print(f"could not start ComfyUI: {r.stderr.strip()}")
            return 1
        t0 = time.time()
        while not comfy_up(config):
            if not _unit_active(COMFY_UNIT):
                print("ComfyUI exited during start-up; last log lines:")
                log = DIRS["logs"] / "comfyui.log"
                print("".join(log.read_text(errors="replace").splitlines(True)[-15:]) if log.is_file() else "(no log)")
                return 1
            if time.time() - t0 > timeout:
                print(f"ComfyUI did not answer within {timeout:.0f} s; see logs/comfyui.log")
                return 1
            time.sleep(3)
        print(f"ComfyUI: up after {time.time() - t0:.0f} s")
    if _unit_active(STUDIO_UNIT):
        print("inbox service: already running")
    else:
        r = _systemctl("start", STUDIO_UNIT)
        if r.returncode:
            print(f"could not start the inbox service: {r.stderr.strip()}")
            return 1
        time.sleep(2)
        print("inbox service: running" if _unit_active(STUDIO_UNIT) else "inbox service FAILED, see logs/studio.log")
    print(f"\nStudio ready. Drop scripts into {DIRS['inbox']}\nFinished videos appear in {DIRS['output']}\nStop everything with: studio stop")
    return 0


def stop(config: Config) -> int:
    st = json.loads(STATUS.read_text()) if STATUS.is_file() else {}
    if st.get("state") == "rendering":
        print(f"note: '{st.get('project')}' was rendering; it goes back to the inbox and resumes on the next start")
    _systemctl("stop", STUDIO_UNIT)
    print("inbox service: stopped")
    if _unit_active(COMFY_UNIT):
        _systemctl("stop", COMFY_UNIT)
        print("ComfyUI: stopped (GPU memory freed)")
    elif comfy_up(config):
        print("ComfyUI: left running (it was started outside the studio, e.g. in tmux)")
    _status(state="stopped")
    return 0


# ------------------------------------------------------------------------- extra thumbnails


def thumbnail_cmd(config: Config, a) -> int:
    from pipeline.script import EXPRESSIONS, ThumbCharacter, Thumbnail
    from pipeline.thumbnails import make_custom

    library = library_or_none(config)
    character = None
    if a.character:
        # name[:expression[:side[:pose]]]
        parts = a.character.split(":")
        name = parts[0]
        expression = parts[1] if len(parts) > 1 and parts[1] else "shocked"
        side = parts[2] if len(parts) > 2 and parts[2] else "right"
        pose = parts[3] if len(parts) > 3 and parts[3] else "talk_front"
        problems = []
        if library is None:
            problems.append("the character library is missing")
        else:
            if name not in library.characters():
                problems.append(f"unknown character '{name}' (have: {', '.join(library.characters())})")
            elif not library.has_pose(name, pose):
                problems.append(f"{name} has no pose '{pose}' (have: {', '.join(library.poses(name))})")
        if expression not in EXPRESSIONS:
            problems.append(f"unknown expression '{expression}' (use one of {', '.join(EXPRESSIONS)})")
        if side not in ("left", "right"):
            problems.append(f"side must be left or right, not '{side}'")
        if problems:
            print("Cannot make the thumbnail:\n" + "\n".join(f"  - {p}" for p in problems))
            return 1
        character = ThumbCharacter(name=name, pose=pose, expression=expression, side=side)
    if len(a.text) > 32:
        print(f"--text is {len(a.text)} characters; keep it to 32 (1-4 big words).")
        return 1
    style, out_root = a.style or "", DIRS["output"] / "_thumbnails"
    if a.project:
        run_script = config.paths.runs_dir / a.project / "script.json"
        if run_script.is_file():
            style = style or json.loads(run_script.read_text()).get("style", "")
        out_root = DIRS["output"] / a.project / "thumbnails_extra"
    out_dir = out_root / _stamp()
    thumb = Thumbnail(description=a.description, concept="manual", image_prompt=a.description,
                      text=a.text, text_position=a.position, character=character)
    if not comfy_up(config):
        print(f"ComfyUI is not running at {config.comfy.url}; run: studio start")
        return 1
    with gpu_lock():
        results = make_custom(config, thumb, out_dir, library, style=style, variants=a.variants,
                              seed=a.seed if a.seed is not None else int(time.time()) % 100000)
    print("\n".join(str(p) for p in results))
    print(f"compare sheet: {out_dir / 'thumbnails_compare.jpg'}")
    return 0


# ------------------------------------------------------------------------- voices


def voice_cmd(config: Config, a) -> int:
    from pipeline.voices import design_voice

    if not comfy_up(config):
        print(f"ComfyUI is not running at {config.comfy.url}; run: studio start")
        return 1
    print(f"designing voice '{a.name}'... (the first run loads the VoiceDesign model, ~1-2 min)")
    try:
        with gpu_lock():
            r = design_voice(config, a.name, a.description, DIRS["output"] / "_voices",
                             text=a.text, seed=a.seed, overwrite=a.force)
    except (ValueError, FileExistsError, RuntimeError) as e:
        print(f"Cannot make the voice: {e}")
        return 1
    print(f"saved: {r['wav']}  ({r['seconds']} s, seed {r['seed']})")
    print(f"listen: {r['preview']}")
    if a.name not in config.tts.voices:
        print(f"\nTo use it in scripts, add {a.name} to tts.voices in config.yaml, then tag lines like:\n"
              f"  [{a.name}|temperature:0.8] Hello there!")
    print("Not happy with it? Run again with --force (a new random seed) or a different description.")
    return 0


# ------------------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="studio", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check"); c.add_argument("script", type=Path)
    m = sub.add_parser("make"); m.add_argument("script", type=Path)
    m.add_argument("--until", choices=STAGE_ORDER, default="thumbnails", help="stop after this stage (oversight)")
    m.add_argument("--only-scene", action="append", default=[], help="redo only this scene id (repeatable)")
    m.add_argument("--force", action="store_true", help="regenerate even if cached")
    r = sub.add_parser("review"); r.add_argument("project")
    sub.add_parser("status")
    sub.add_parser("watch")
    sub.add_parser("start")
    sub.add_parser("stop")
    t = sub.add_parser("thumbnail", help="extra thumbnails from a description (the script's own 3 are kept)")
    t.add_argument("description", help="what the picture shows, e.g. 'Caesar laughing at pirates in a ship cabin'")
    t.add_argument("--text", default="", help="1-4 big words drawn on the thumbnail ('' = none)")
    t.add_argument("--character", help="mascot cut-out: name[:expression[:side[:pose]]], e.g. apprentice:shocked:right")
    t.add_argument("--position", choices=["left", "right", "top", "bottom"], help="where the text goes (default: opposite the mascot, else bottom)")
    t.add_argument("--project", help="save into output/<project>/thumbnails_extra/ and use that video's era style")
    t.add_argument("--style", help="era/setting text (default: the project's style, if --project is given)")
    t.add_argument("--variants", type=int, default=3, choices=range(1, 7), metavar="1-6", help="how many versions (default 3)")
    t.add_argument("--seed", type=int, help="fixed seed to reproduce a result")
    v = sub.add_parser("voice", help="design a new character voice from a description")
    v.add_argument("name", help="voice name used in script tags, e.g. narrator2 or old_sailor")
    v.add_argument("description", help="age, gender, pitch, tone, pace, accent, e.g. 'elderly British woman, warm, slow'")
    v.add_argument("--text", default="", help="what the reference clip says (default: a short neutral paragraph)")
    v.add_argument("--seed", type=int, help="fixed seed to reproduce a voice")
    v.add_argument("--force", action="store_true", help="replace an existing voice with this name")
    a = ap.parse_args(argv)
    config = load_config()
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)

    if a.cmd == "watch":
        watch(config)
        return 0
    if a.cmd == "thumbnail":
        return thumbnail_cmd(config, a)
    if a.cmd == "voice":
        return voice_cmd(config, a)
    if a.cmd == "start":
        return start(config)
    if a.cmd == "stop":
        return stop(config)
    if a.cmd == "check":
        rep = check_file(a.script, config, library_or_none(config))
        print(rep.text())
        return 0 if rep.ok else 1
    if a.cmd == "make":
        rep = check_file(a.script, config, library_or_none(config))
        print(rep.text())
        if not rep.ok:
            return 1
        if not comfy_up(config):
            print(f"ComfyUI is not running at {config.comfy.url}; start it first.")
            return 1
        console = Console()
        with gpu_lock():
            directory = render_script(config, rep.script, console, a.until, a.only_scene or None, a.force)
        r = review(directory)
        print(f"\nrun folder: {directory}")
        print("review sheets: " + ", ".join(r["sheets"].values()))
        if a.until == "thumbnails":
            log = DIRS["logs"] / f"{rep.script.project}_{_stamp()}_manual.log"
            log.write_text(rep.text())
            dest = publish(config, rep.script, a.script, log)
            print(f"published: {dest}  ({'all checks passed' if r.get('passed') else 'some checks FAILED, see report.md'})")
        _status(state="idle", last=f"manual make {rep.script.project} (until {a.until})")
        return 0
    if a.cmd == "review":
        directory = config.paths.runs_dir / a.project
        if not (directory / "script.json").is_file():
            print(f"no run found at {directory}")
            return 1
        r = review(directory)
        print((directory / "review" / "report.md").read_text())
        return 0
    if a.cmd == "status":
        st = json.loads(STATUS.read_text()) if STATUS.is_file() else {"state": "unknown (service never ran)"}
        print("service:", json.dumps(st))
        print("ComfyUI:", "up" if comfy_up(config) else "DOWN")
        for name in ("inbox", "processing", "failed", "done"):
            files = sorted(p.name for p in DIRS[name].glob("*.json"))
            print(f"{name:10s} {len(files):3d}  {', '.join(files[-5:])}")
        outs = sorted(DIRS["output"].iterdir(), key=lambda p: p.stat().st_mtime)[-5:] if DIRS["output"].exists() else []
        print("latest outputs:", ", ".join(p.name for p in outs) or "-")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

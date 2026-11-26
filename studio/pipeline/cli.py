from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pipeline import __version__
from pipeline import runner
from pipeline.config import load_config
from pipeline.doctor import run_doctor
from pipeline.script import load_script


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pipeline", description="Faceless AI video pipeline")
    parser.add_argument("--config", default=None, help="path to config.yaml")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check environment, models, voices, ComfyUI")
    doctor.add_argument("--strict", action="store_true", help="treat warnings as failures")

    validate = sub.add_parser("validate", help="validate a script JSON")
    validate.add_argument("script", type=Path)

    sub.add_parser("version", help="print version")

    for name, help_text in (
        ("plan", "print the job plan"),
        ("run", "run the pipeline"),
        ("clean", "remove intermediates"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("script", type=Path, nargs="?")
        command.add_argument("--stage", default="all", choices=["all", "audio", "images", "video", "compose", "render"])
        command.add_argument("--only-scene", action="append", default=[])
        command.add_argument("--force", action="store_true")
        if name == "clean":
            command.add_argument("--keep-final", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0

    config = load_config(args.config)

    if args.command == "doctor":
        return run_doctor(config, strict=args.strict)

    if args.command in {"validate", "plan", "run", "clean"}:
        if args.script is None:
            print(f"{args.command}: a script path is required", file=sys.stderr)
            return 2
        try:
            script = load_script(args.script)
            script.validate_against(config.tts.voices)
        except (OSError, ValueError) as exc:
            print(f"invalid script: {exc}", file=sys.stderr)
            return 1

    if args.command == "validate":
        print(f"ok: project '{script.project}', {len(script.scenes)} scene(s), voices {script.voice_names()}")
        return 0

    if args.command == "plan":
        runner.plan(config, script, only_scenes=args.only_scene)
        return 0

    if args.command == "run":
        try:
            final = runner.run(
                config,
                script,
                stage=args.stage,
                only_scenes=args.only_scene,
                force=args.force,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"run failed: {exc}", file=sys.stderr)
            return 1
        print(f"output: {final}")
        return 0

    if args.command == "clean":
        runner.clean(config, script, only_scenes=args.only_scene)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

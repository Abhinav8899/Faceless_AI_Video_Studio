"""Automatic likeness check for consistent subjects (no human needed).

The models need torch, so they run in ComfyUI's Python as a small worker process
(pipeline/likeness_worker.py) that this class starts once and talks to over JSON lines.
If the worker cannot start (models missing, no torch), the check is skipped with a warning:
a render never fails because of it.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from pipeline.config import Config

WORKER = Path(__file__).with_name("likeness_worker.py")


class LikenessChecker:
    def __init__(self, config: Config, log=print) -> None:
        self.cfg = config.subjects
        self.log = log
        self.proc: subprocess.Popen | None = None
        self.failed = not self.cfg.check

    def _start(self) -> bool:
        if self.proc is not None:
            return True
        if self.failed:
            return False
        if not Path(self.cfg.python).is_file():
            self.log(f"likeness check off: {self.cfg.python} not found")
            self.failed = True
            return False
        env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_VERBOSITY="error", TOKENIZERS_PARALLELISM="false")
        args = json.dumps({"detector": self.cfg.detector, "embedder": self.cfg.embedder, "device": self.cfg.device})
        self.proc = subprocess.Popen([str(self.cfg.python), str(WORKER), args], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)
        ready = self.proc.stdout.readline()
        if '"ready"' not in ready:
            self.log("likeness check off: the worker did not start (are the models downloaded? see README)")
            self.close()
            self.failed = True
            return False
        return True

    def _ask(self, req: dict) -> dict | None:
        if not self._start():
            return None
        try:
            self.proc.stdin.write(json.dumps(req) + "\n")
            self.proc.stdin.flush()
            res = json.loads(self.proc.stdout.readline())
        except (OSError, ValueError) as exc:
            self.log(f"likeness check off: worker stopped ({exc})")
            self.close()
            self.failed = True
            return None
        if "error" in res:
            self.log(f"likeness check: {res['error']}")
            return None
        return res

    @property
    def available(self) -> bool:
        return self._start()

    def inspect(self, image: Path, noun: str) -> dict | None:
        return self._ask({"op": "inspect", "image": str(image), "noun": noun})

    def score(self, image: Path, reference: Path, noun: str, person: bool) -> dict | None:
        return self._ask({"op": "score", "image": str(image), "reference": str(reference), "noun": noun,
                          "person": person, "min_area": self.cfg.min_area})

    def close(self) -> None:
        if self.proc is not None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=10)
            except Exception:
                self.proc.kill()
            self.proc = None

    def __enter__(self) -> "LikenessChecker":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

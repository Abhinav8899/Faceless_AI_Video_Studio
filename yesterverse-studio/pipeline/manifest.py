from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class Manifest:
    def __init__(self, path: Path, data: dict[str, Any]) -> None:
        self.path = path
        self.data = data

    @classmethod
    def load_or_create(cls, path: Path, project: str) -> "Manifest":
        if path.exists():
            return cls(path, json.loads(path.read_text()))
        return cls(path, {"version": 1, "project": project, "scenes": {}, "runs": {}})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.path.parent, delete=False, prefix=self.path.name, suffix=".tmp"
        )
        try:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)

    def scene(self, scene_id: str) -> dict[str, Any]:
        scenes = self.data.setdefault("scenes", {})
        return scenes.setdefault(scene_id, {"stages": {}})

    def stage_status(self, scene_id: str, stage: str) -> str | None:
        return self.scene(scene_id).get("stages", {}).get(stage, {}).get("status")

    def set_stage(self, scene_id: str, stage: str, status: str, **extra: Any) -> None:
        stages = self.scene(scene_id).setdefault("stages", {})
        entry = stages.setdefault(stage, {})
        entry["status"] = status
        entry.update(extra)
        self.save()

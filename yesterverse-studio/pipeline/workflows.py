from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

Node = dict[str, Any]
Prompt = dict[str, Node]

SAVE_CLASSES = ("SaveImage", "SaveAudioAdvanced", "SaveVideo")


class WorkflowError(RuntimeError):
    pass


def link_target(value: Any) -> str | None:
    if (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
    ):
        return value[0]
    return None


def validate_structure(prompt: Prompt) -> None:
    if not isinstance(prompt, dict) or not prompt:
        raise WorkflowError("workflow prompt is empty or not an object")
    for node_id, node in prompt.items():
        if not isinstance(node, dict):
            raise WorkflowError(f"node {node_id} is not an object")
        if not isinstance(node.get("class_type"), str):
            raise WorkflowError(f"node {node_id} has no class_type")
        if not isinstance(node.get("inputs"), dict):
            raise WorkflowError(f"node {node_id} has no inputs object")
    for node_id, node in prompt.items():
        for name, value in node["inputs"].items():
            target = link_target(value)
            if target is not None and target not in prompt:
                raise WorkflowError(f"node {node_id}.{name} links to missing node {target}")


class Workflow:
    def __init__(self, data: Prompt, source: Path | None = None, name: str = "") -> None:
        validate_structure(data)
        self.data: Prompt = copy.deepcopy(data)
        self.source = source
        self.name = name

    @classmethod
    def load(cls, path: str | Path, name: str = "") -> "Workflow":
        source = Path(path)
        data = json.loads(source.read_text())
        return cls(data, source, name or source.stem)

    def clone(self) -> "Workflow":
        return Workflow(self.data, self.source, self.name)

    def nodes(self, class_type: str) -> list[tuple[str, Node]]:
        return [(node_id, node) for node_id, node in self.data.items() if node.get("class_type") == class_type]

    def find(self, class_type: str, title_contains: str | None = None) -> list[tuple[str, Node]]:
        matches: list[tuple[str, Node]] = []
        for node_id, node in self.nodes(class_type):
            title = (node.get("_meta") or {}).get("title") or ""
            if title_contains is None or title_contains.lower() in title.lower():
                matches.append((node_id, node))
        return matches

    def one(self, class_type: str, title_contains: str | None = None) -> tuple[str, Node]:
        matches = self.find(class_type, title_contains)
        if len(matches) != 1:
            titles = [((node.get("_meta") or {}).get("title") or "?") for _, node in matches]
            raise WorkflowError(
                f"expected exactly one {class_type} (title~{title_contains!r}) in {self.name}, found {len(matches)}: {titles}"
            )
        return matches[0]

    def set(self, class_type: str, input_name: str, value: Any, title_contains: str | None = None) -> None:
        _, node = self.one(class_type, title_contains)
        node["inputs"][input_name] = value

    def set_node(self, node_id: str, input_name: str, value: Any) -> None:
        if node_id not in self.data:
            raise WorkflowError(f"node {node_id} not found in {self.name}")
        self.data[node_id]["inputs"][input_name] = value

    def add_node(self, node_id: str, class_type: str, inputs: dict[str, Any], title: str) -> str:
        if node_id in self.data:
            raise WorkflowError(f"node {node_id} already exists in {self.name}")
        self.data[node_id] = {
            "class_type": class_type,
            "inputs": dict(inputs),
            "_meta": {"title": title},
        }
        return node_id

    def save_nodes(self) -> list[tuple[str, Node]]:
        return [
            (node_id, node)
            for node_id, node in self.data.items()
            if node.get("class_type") in SAVE_CLASSES
        ]

    def set_save_prefix(self, prefix: str) -> None:
        nodes = self.save_nodes()
        if not nodes:
            raise WorkflowError(f"{self.name} has no save/output node")
        for _, node in nodes:
            node["inputs"]["filename_prefix"] = prefix

    def dump(self) -> Prompt:
        return copy.deepcopy(self.data)

    def sha256(self) -> str:
        canonical = json.dumps(self.data, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

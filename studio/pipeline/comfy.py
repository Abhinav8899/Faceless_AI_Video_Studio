from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from pipeline.config import ComfyConfig


class ComfyError(RuntimeError):
    pass


class ComfyClient:
    def __init__(self, config: ComfyConfig) -> None:
        self.config = config
        self.client = httpx.Client(
            base_url=config.url.rstrip("/"),
            timeout=httpx.Timeout(config.request_timeout, connect=10.0),
        )
        self.client_id = str(uuid.uuid4())

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "ComfyClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def system_stats(self) -> dict[str, Any]:
        response = self.client.get("/system_stats")
        response.raise_for_status()
        return response.json()

    def queue(self) -> dict[str, Any]:
        response = self.client.get("/queue")
        response.raise_for_status()
        return response.json()

    def object_info(self, node_class: str) -> dict[str, Any]:
        response = self.client.get(f"/object_info/{node_class}")
        response.raise_for_status()
        return response.json()

    def submit(self, prompt: dict[str, Any]) -> str:
        payload = {"prompt": prompt, "client_id": self.client_id}
        response = self.client.post("/prompt", json=payload)
        if response.status_code >= 400:
            raise ComfyError(f"ComfyUI rejected prompt: {response.status_code} {response.text}")
        body = response.json()
        if "prompt_id" not in body:
            raise ComfyError(f"ComfyUI response missing prompt_id: {body}")
        return body["prompt_id"]

    def history(self, prompt_id: str) -> dict[str, Any]:
        response = self.client.get(f"/history/{prompt_id}")
        response.raise_for_status()
        return response.json()

    def wait(self, prompt_id: str, timeout: float = 3600.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = self.history(prompt_id)
            entry = data.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise ComfyError(f"prompt {prompt_id} failed: {json.dumps(status)[:2000]}")
                if status.get("completed") or entry.get("outputs"):
                    return entry
            time.sleep(self.config.poll_interval)
        raise ComfyError(f"prompt {prompt_id} timed out after {timeout:.0f}s")

    def upload_image(self, path: str | Path, subfolder: str = "pipeline") -> str:
        path = Path(path)
        mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
        with path.open("rb") as handle:
            files = {"image": (path.name, handle, mime)}
            data = {"overwrite": "true", "type": "input", "subfolder": subfolder}
            response = self.client.post(
                "/upload/image",
                files=files,
                data=data,
                timeout=httpx.Timeout(self.config.upload_timeout, connect=10.0),
            )
        response.raise_for_status()
        body = response.json()
        name = body.get("name", path.name)
        folder = body.get("subfolder", "")
        return f"{folder}/{name}" if folder else name

    def view(self, filename: str, subfolder: str = "", folder_type: str = "output") -> bytes:
        response = self.client.get(
            "/view",
            params={"filename": filename, "subfolder": subfolder, "type": folder_type},
        )
        response.raise_for_status()
        return response.content

    @staticmethod
    def first_output(entry: dict[str, Any]) -> dict[str, Any] | None:
        for node_output in (entry.get("outputs") or {}).values():
            for value in node_output.values():
                if not isinstance(value, list):
                    continue
                for item in value:
                    if isinstance(item, dict) and item.get("filename"):
                        return item
        return None

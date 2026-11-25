from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.comfy import ComfyClient
from pipeline.workflows import Workflow, WorkflowError


@dataclass(frozen=True)
class JobResult:
    prompt_id: str
    filename: str
    subfolder: str
    folder_type: str
    path: Path
    elapsed: float
    entry: dict[str, Any]


def run_job(client: ComfyClient, workflow: Workflow, destination: Path, timeout: float) -> JobResult:
    start = time.monotonic()
    prompt_id = client.submit(workflow.dump())
    entry = client.wait(prompt_id, timeout)
    output = client.first_output(entry)
    if output is None:
        raise WorkflowError(f"prompt {prompt_id} finished without a file output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = client.view(
        output.get("filename", ""),
        output.get("subfolder", ""),
        output.get("type", "output"),
    )
    destination.write_bytes(data)
    return JobResult(
        prompt_id=prompt_id,
        filename=output.get("filename", ""),
        subfolder=output.get("subfolder", ""),
        folder_type=output.get("type", "output"),
        path=destination,
        elapsed=time.monotonic() - start,
        entry=entry,
    )

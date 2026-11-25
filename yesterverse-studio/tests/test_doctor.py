from pathlib import Path

from pipeline.config import Config, PathsConfig
from pipeline.doctor import FAIL, OK, WARN, check_disk, check_models, check_voices, check_workflows


def make_config(tmp_path: Path) -> Config:
    comfy = tmp_path / "ComfyUI"
    project = tmp_path / "youtube"
    return Config(
        paths=PathsConfig(
            comfyui_root=comfy,
            project_root=project,
            workflows_dir=project / "workflows",
            runs_dir=project / "runs",
            refs_dir=project / "refs",
        )
    )


def test_models_ok_and_missing(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    for _, path in config.models.entries(config.paths.comfyui_root):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    assert check_models(config).status == OK
    config.models.entries(config.paths.comfyui_root)[0][1].unlink()
    result = check_models(config)
    assert result.status == FAIL
    assert "flux-2-klein-4b.safetensors" in result.detail


def test_voices_check(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    voices_dir = config.paths.voices_dir
    voices_dir.mkdir(parents=True)
    for voice in config.tts.voices:
        (voices_dir / f"{voice}.wav").write_bytes(b"x")
        (voices_dir / f"{voice}.txt").write_text("hello")
    assert check_voices(config).status == OK
    (voices_dir / "inventor.wav").unlink()
    result = check_voices(config)
    assert result.status == FAIL
    assert "inventor.wav" in result.detail


def test_workflows_pending_and_present(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.paths.workflows_dir.mkdir(parents=True)
    pending = check_workflows(config)
    assert pending.status == WARN
    assert "tts.api.json" in pending.detail
    (config.paths.workflows_dir / "api").mkdir(parents=True)
    for name in ("tts", "image", "edit", "i2v"):
        config.workflows.path(config.paths.workflows_dir, name).write_text(
            '{"1": {"class_type": "SaveImage", "inputs": {}}}'
        )
    assert check_workflows(config).status == OK


def test_disk_check(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    config.paths.runs_dir.mkdir(parents=True)
    config.disk.min_free_gb = 0
    assert check_disk(config).status == OK

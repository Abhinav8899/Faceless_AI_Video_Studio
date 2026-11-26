import io
from pathlib import Path

from rich.console import Console

from pipeline import runner
from pipeline.config import Config, PathsConfig
from pipeline.script import Script


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


def test_clean_keeps_final_and_full_audio(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    script = Script.model_validate(
        {
            "project": "demo",
            "scenes": [
                {
                    "id": "01",
                    "narration": "hello",
                    "image_prompt": "x",
                    "motion_prompt": "y",
                }
            ],
        }
    )
    directory = runner.run_dir(config, script)
    files = [
        directory / "images" / "scene_01.png",
        directory / "video" / "scene_01" / "clip_01.mp4",
        directory / "scenes" / "scene_01.mp4",
        directory / "render" / "scene_01.mp4",
        directory / "audio" / "scene_01.flac",
        directory / "audio" / "full.flac",
        directory / "final.mp4",
        directory / "manifest.json",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    runner.clean(config, script, console=Console(file=io.StringIO()))
    assert not (directory / "images").exists()
    assert not (directory / "video").exists()
    assert not (directory / "scenes").exists()
    assert not (directory / "render").exists()
    assert not (directory / "audio" / "scene_01.flac").exists()
    assert (directory / "audio" / "full.flac").is_file()
    assert (directory / "final.mp4").is_file()
    assert (directory / "manifest.json").is_file()


def test_clean_only_scene_preserves_others(tmp_path: Path) -> None:
    config = make_config(tmp_path)
    script = Script.model_validate(
        {
            "project": "demo",
            "scenes": [
                {"id": "01", "narration": "a", "image_prompt": "x", "motion_prompt": "y"},
                {"id": "02", "narration": "b", "image_prompt": "x", "motion_prompt": "y"},
            ],
        }
    )
    directory = runner.run_dir(config, script)
    for scene_id in ("01", "02"):
        for path in (
            directory / "images" / f"scene_{scene_id}.png",
            directory / "video" / f"scene_{scene_id}" / "clip_01.mp4",
            directory / "scenes" / f"scene_{scene_id}.mp4",
            directory / "render" / f"scene_{scene_id}.mp4",
            directory / "audio" / f"scene_{scene_id}.flac",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")
    runner.clean(config, script, only_scenes=["01"], console=Console(file=io.StringIO()))
    assert not (directory / "images" / "scene_01.png").exists()
    assert not (directory / "video" / "scene_01").exists()
    assert not (directory / "scenes" / "scene_01.mp4").exists()
    assert not (directory / "render" / "scene_01.mp4").exists()
    assert not (directory / "audio" / "scene_01.flac").exists()
    assert (directory / "images" / "scene_02.png").is_file()
    assert (directory / "video" / "scene_02" / "clip_01.mp4").is_file()
    assert (directory / "scenes" / "scene_02.mp4").is_file()
    assert (directory / "render" / "scene_02.mp4").is_file()
    assert (directory / "audio" / "scene_02.flac").is_file()

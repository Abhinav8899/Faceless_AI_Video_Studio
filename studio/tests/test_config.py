from pathlib import Path

from pipeline.config import Config, load_config


def test_defaults() -> None:
    config = Config()
    assert config.media.flux.width == 1024
    assert config.media.wan.width == 848
    assert config.media.render.width == 1920
    assert config.tts.narrator_voice == "nar.wav"
    assert config.workflows.path(config.paths.workflows_dir, "tts").as_posix().endswith("workflows/api/tts.api.json")


def test_load_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "media:\n  wan:\n    width: 864\ntts:\n  language: English\n  voices: [nar, pip]\n"
    )
    config = load_config(config_file)
    assert config.media.wan.width == 864
    assert config.media.wan.height == 480
    assert config.tts.voices == ["nar", "pip"]


def test_missing_config_returns_defaults(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nope.yaml")
    assert config.comfy.url == "http://127.0.0.1:8188"

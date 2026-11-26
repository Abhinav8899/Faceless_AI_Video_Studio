from pipeline.timing import (
    clip_seed,
    plan_clips,
    render_duration,
    scene_tail,
    wan_frames,
)


def test_wan_frames_on_four_plus_one_grid() -> None:
    assert wan_frames(5.0, 16) == 81
    assert (wan_frames(2.3, 16) - 1) % 4 == 0
    assert wan_frames(0.1, 16) >= 9


def test_plan_clips_covers_target_without_big_overshoot() -> None:
    frames = plan_clips(7.3, 16, 5.0)
    total = sum(frames) / 16
    assert total >= 7.3
    assert total - 7.3 < 0.3
    assert all((count - 1) % 4 == 0 for count in frames)


def test_plan_clips_single_short_scene() -> None:
    frames = plan_clips(1.0, 16, 5.0)
    assert frames == [17]


def test_render_duration_aligns_to_frame() -> None:
    duration = render_duration(7.312, 30)
    assert abs(duration * 30 - round(duration * 30)) < 1e-9


def test_scene_tail_and_seed() -> None:
    assert scene_tail(None, 0.25, 0.15) == 0.4
    assert scene_tail(0.5, 0.25, 0.15) == 0.65
    assert clip_seed(10, 2) == 12

"""Tests for shorts_generator.smartcrop — face-based crop planning (no OpenCV needed)."""
import pytest

from shorts_generator.smartcrop import (
    _rolling_median,
    compute_crop_window,
    plan_crop_segments,
)


def test_rolling_median_preserves_length():
    out = _rolling_median([0.5, 0.8, 0.9, 0.1, 0.2], 3)
    assert len(out) == 5
    # spikes smoothed: index 3 (0.1) surrounded by 0.9,0.1,0.2 -> median 0.2
    assert out[3] == 0.2


def test_plan_crop_no_faces_returns_empty():
    assert plan_crop_segments([], 60.0) == []


def test_plan_crop_single_face_stays_center():
    samples = [(float(i) * 0.5, 0.5, 0.4, 0.1) for i in range(120)]  # 60s, face at center
    segments = plan_crop_segments(samples, 60.0)
    assert len(segments) == 1
    start, end, x = segments[0]
    assert start == pytest.approx(0.0)
    assert end == pytest.approx(60.0)
    assert 0.44 <= x <= 0.56  # center bin


def test_plan_crop_follows_face_movement():
    # face moves left -> right halfway through
    samples = []
    for i in range(120):
        t = i * 0.5
        cx = 0.2 if t < 30 else 0.8
        samples.append((t, cx, 0.4, 0.1))
    segments = plan_crop_segments(samples, 60.0)
    assert len(segments) >= 2
    assert segments[0][2] < 0.5  # left half
    assert segments[-1][2] > 0.5  # right half
    # segments are time-ordered and non-overlapping
    for a, b in zip(segments, segments[1:], strict=False):
        assert a[1] <= b[0]


def test_compute_crop_window_landscape():
    win = compute_crop_window(1920, 1080, 1080, 1920, 0.0)
    assert win["w"] == 607  # int(1080 * 9/16)
    assert win["h"] == 1080
    assert win["x"] == 0
    win2 = compute_crop_window(1920, 1080, 1080, 1920, 1.0)
    assert win2["x"] == 1920 - 607  # right edge


def test_compute_crop_window_portrait():
    win = compute_crop_window(1080, 1920, 1080, 1920, 0.5)
    assert win["w"] == 1080 and win["h"] == 1920  # already 9:16, no crop


def test_compute_crop_window_square():
    win = compute_crop_window(1080, 1080, 1080, 1920, 0.5)
    assert win["w"] == 607  # crop square to 9:16

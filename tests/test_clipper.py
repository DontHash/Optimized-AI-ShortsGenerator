"""Tests for shorts_generator.clipper — SRT building (no ffmpeg needed)."""
from shorts_generator.clipper import _slugify, _srt_timestamp, build_clip_srt


def test_srt_timestamp_format():
    assert _srt_timestamp(0) == "00:00:00,000"
    assert _srt_timestamp(65.25) == "00:01:05,250"


def test_slugify():
    assert _slugify("The One Mistake That Cost Me $50K!") == "the-one-mistake-that-cost-me-50k"
    assert _slugify("") == "clip"
    assert _slugify("x" * 90)[:60] == "x" * 60


def test_build_clip_srt_rebases_to_clip(tmp_path):
    segments = [
        {"start": 100.0, "end": 103.0, "text": "the big mistake"},
        {"start": 103.0, "end": 106.0, "text": "cost me everything"},
        {"start": 200.0, "end": 205.0, "text": "outside the clip"},
    ]
    out = tmp_path / "clip.srt"
    build_clip_srt(segments, clip_start=100.0, clip_end=106.0, out_path=str(out))
    content = out.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:03,000" in content  # rebased
    assert "cost me everything" in content
    assert "outside the clip" not in content  # outside window dropped
    assert "the big mistake" in content

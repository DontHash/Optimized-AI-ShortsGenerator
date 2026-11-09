"""Tests for shorts_generator.clipper — SRT building (no ffmpeg needed)."""
from shorts_generator.clipper import (
    _normalize_crop_segments,
    _slugify,
    _srt_timestamp,
    build_clip_srt,
    chunk_words_to_cues,
)


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


def test_normalize_crop_segments_prepends_intro_and_fills_gaps():
    out = _normalize_crop_segments([(2.0, 5.0, 0.2), (7.0, 10.0, 0.8)], 12.0)
    assert out[0][0] == 0.0
    assert out[0][1] >= 5.0  # intro + first segment (merged when x matches)
    assert out[-1][1] == 12.0  # tail covered
    # no gaps
    for (_, end, _), (start, _, _) in zip(out, out[1:], strict=False):
        assert abs(end - start) < 1e-6


def test_normalize_crop_segments_empty_falls_back_to_center():
    assert _normalize_crop_segments([], 10.0) == [(0.0, 10.0, 0.5)]


def test_chunk_words_to_cues_accepts_text_and_clamps_overlap():
    words = [
        {"start": 0.0, "end": 0.5, "text": "one"},
        {"start": 0.5, "end": 1.0, "text": "two"},
        {"start": 1.0, "end": 1.5, "text": "three"},
    ]
    cues = chunk_words_to_cues(words, max_words=2)
    assert len(cues) == 2
    assert cues[0]["end"] <= cues[1]["start"] + 0.001

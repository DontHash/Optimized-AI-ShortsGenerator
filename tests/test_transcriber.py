"""Tests for shorts_generator.transcriber — SRT parsing + timestamp formatting (no Whisper)."""
from shorts_generator.transcriber import _parse_srt_timestamp, format_srt_timestamp, load_srt_file

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
hello world

2
00:00:02,500 --> 00:00:05,000
the big mistake

3
00:00:05,000 --> 00:00:08,000
the secret
"""


def test_format_srt_timestamp():
    assert format_srt_timestamp(0) == "00:00:00,000"
    assert format_srt_timestamp(2.5) == "00:00:02,500"
    assert format_srt_timestamp(3661.5) == "01:01:01,500"


def test_parse_srt_timestamp_roundtrip():
    assert _parse_srt_timestamp("00:00:02,500") == 2.5
    assert _parse_srt_timestamp("01:02:03,000") == 3723.0


def test_load_srt_file_parses_segments(tmp_path):
    p = tmp_path / "sample.srt"
    p.write_text(SAMPLE_SRT, encoding="utf-8")
    out = load_srt_file(p)
    assert out["duration"] == 8.0
    assert len(out["segments"]) == 3
    assert out["segments"][0]["text"] == "hello world"
    assert out["segments"][1]["start"] == 2.5


def test_load_srt_file_empty(tmp_path):
    p = tmp_path / "empty.srt"
    p.write_text("", encoding="utf-8")
    out = load_srt_file(p)
    assert out["segments"] == []
    assert out["duration"] == 0.0


def test_load_srt_file_bom_tolerant(tmp_path):
    p = tmp_path / "bom.srt"
    p.write_text("\ufeff" + SAMPLE_SRT, encoding="utf-8")
    out = load_srt_file(p)
    assert len(out["segments"]) == 3

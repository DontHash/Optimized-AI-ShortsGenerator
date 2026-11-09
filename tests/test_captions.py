"""Tests for shorts_generator.captions — ASS timing and safe-zone generation."""

from shorts_generator.captions import _ass_timestamp, _chunk_words, build_ass


def test_ass_timestamp_carries_centiseconds():
    assert _ass_timestamp(0) == "0:00:00.00"
    assert _ass_timestamp(1.999) == "0:00:02.00"  # no invalid .100
    assert _ass_timestamp(65.25) == "0:01:05.25"


def test_chunk_words_accepts_word_and_text_keys():
    words = [
        {"start": 0.0, "end": 0.3, "word": "hello"},
        {"start": 0.3, "end": 0.6, "text": "world"},
    ]
    chunks = _chunk_words(words, max_words=4)
    assert chunks
    assert [w["text"] for w in chunks[0]] == ["hello", "world"]


def test_build_ass_word_events_use_1080x1920_and_safe_zone(tmp_path):
    words = [{"start": i * 0.4, "end": i * 0.4 + 0.35, "word": f"w{i}"} for i in range(6)]
    out = tmp_path / "captions.ass"
    build_ass(words, str(out), clip_start=0.0, clip_end=2.4)

    content = out.read_text(encoding="utf-8")
    assert "PlayResX: 1080" in content
    assert "PlayResY: 1920" in content
    assert "MarginV, Encoding" in content
    assert ",360,1" in content  # bottom safe-zone margin
    assert content.count("Dialogue:") >= 2
    assert "&H0000FFFF" in content or "&H00FFFF" in content


def test_build_ass_sentence_fallback_splits_long_segment_and_no_overlap(tmp_path):
    segments = [{"start": 100.0, "end": 130.0, "text": " ".join(["word"] * 30)}]
    out = tmp_path / "fallback.ass"
    build_ass(segments, str(out), clip_start=100.0, clip_end=30.0)

    events = [
        line for line in out.read_text(encoding="utf-8").splitlines()
        if line.startswith("Dialogue:")
    ]
    assert len(events) > 1

    times = []
    for line in events:
        parts = line.split(",", 9)
        start = parts[1].strip()
        end = parts[2].strip()
        times.append((start, end))

    def to_ms(value: str) -> int:
        h, m, rest = value.split(":")
        s, cs = rest.split(".")
        return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(cs) * 10

    for (_, end), (start, _) in zip(times, times[1:], strict=False):
        assert to_ms(end) <= to_ms(start) + 10  # allow rounding only


def test_build_ass_clamps_cues_to_clip_window(tmp_path):
    segments = [
        {"start": 90.0, "end": 95.0, "text": "before"},
        {"start": 101.0, "end": 104.0, "text": "inside"},
        {"start": 111.0, "end": 112.0, "text": "after"},
    ]
    out = tmp_path / "window.ass"
    build_ass(segments, str(out), clip_start=100.0, clip_end=10.0)
    content = out.read_text(encoding="utf-8")
    assert "inside" in content
    assert "before" not in content
    assert "after" not in content

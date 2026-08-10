"""Tests for shorts_generator.highlights — parsing, sanitization, chunking, snapping."""
from shorts_generator import highlights as hl


def test_parse_json_loose_strips_fences():
    out = hl._parse_json_loose("```json\n{\"a\": 1}\n```")
    assert out == {"a": 1}


def test_parse_json_loose_repairs_trailing_comma():
    out = hl._parse_json_loose('{"a": 1, "b": [1, 2,],}')
    assert out == {"a": 1, "b": [1, 2]}


def test_sanitize_highlights_drops_invalid():
    raw = [
        {"title": "ok", "start_time": 5, "end_time": 60, "score": 80},
        {"title": "bad", "start_time": 60, "end_time": 5},     # end<=start
        {"title": "neg", "start_time": -1, "end_time": 10},    # negative start
    ]
    out = hl._sanitize_highlights(raw, duration=100)
    assert len(out) == 1
    assert out[0]["title"] == "ok"


def test_sanitize_highlights_clamps_to_duration():
    out = hl._sanitize_highlights(
        [{"title": "x", "start_time": 90, "end_time": 200, "score": 50}], duration=100
    )
    assert out[0]["end_time"] == 100


def test_sanitize_highlights_clamps_score():
    out = hl._sanitize_highlights(
        [{"title": "x", "start_time": 0, "end_time": 10, "score": 150}], duration=100
    )
    assert out[0]["score"] == 100


def test_salvage_highlights_extracts_flat_objects():
    raw = 'noise {"title":"a","start_time":5,"end_time":60,"score":80,"hook_sentence":"h","virality_reason":"r"} more'
    out = hl._salvage_highlights(raw)
    assert len(out) == 1
    assert out[0]["start_time"] == "5"
    assert out[0]["title"] == "a"


def test_extract_highlights_returns_classification():
    raw = ('{"content_type":"podcast","density":"high","highlights":'
           '[{"title":"x","start_time":5,"end_time":60,"score":80,"hook_sentence":"h","virality_reason":"r"}]}')
    r = hl._extract_highlights(raw, duration=100)
    assert r["content_type"] == "podcast"
    assert r["density"] == "high"
    assert len(r["highlights"]) == 1


def test_extract_highlights_salvage_defaults_classification():
    # broken JSON with a salvageable flat object -> classification defaults
    raw = '{"content_type":"vlog","highlights":[{"title":"y","start_time":10,"end_time":70,"score":70,"hook_sentence":"","virality_reason":""}],'
    r = hl._extract_highlights(raw, duration=100)
    assert r["content_type"] == "other"
    assert r["density"] == "medium"
    assert len(r["highlights"]) == 1


def test_snap_to_sentence_boundaries(segments):
    hs = [{"start_time": 2.2, "end_time": 7.8}]
    out = hl.snap_to_sentence_boundaries(hs, segments, pad=0.3)
    # start snaps back to 2.5 (nearest seg start at/before 2.2 within tol) minus pad
    assert out[0]["start_time"] <= 2.5
    assert out[0]["end_time"] >= 8.0


def test_transcript_excerpt(segments):
    text = hl.transcript_excerpt(segments, 2.0, 8.0)
    assert "big mistake" in text
    assert "secret" in text


def test_dedupe_highlights_time_overlap():
    hs = [
        {"title": "a", "start_time": 0, "end_time": 60, "score": 90},
        {"title": "b", "start_time": 40, "end_time": 100, "score": 70},  # 20s/60s overlap <50%
        {"title": "c", "start_time": 10, "end_time": 50, "score": 60},  # 40s/40s = 100% >50%
    ]
    kept = hl.dedupe_highlights(hs)
    titles = [k["title"] for k in kept]
    assert "c" not in titles  # c almost fully overlaps a


def test_chunk_transcript_offsets_and_rebase():
    transcript = {
        "duration": 2400,
        "segments": [
            {"start": float(i), "end": float(i) + 2, "text": str(i)}
            for i in range(0, 2400, 30)
        ],
    }
    chunks = hl.chunk_transcript(transcript)
    assert len(chunks) >= 2
    assert chunks[0]["_offset"] == 0
    # second chunk offset = 1200 - 60 overlap = 1140
    assert chunks[1]["_offset"] == 1140
    # rebased segment times are chunk-relative (>= 0, <= chunk duration)
    for s in chunks[0]["segments"]:
        assert s["start"] >= 0

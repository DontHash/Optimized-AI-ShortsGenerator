"""Tests for shorts_generator.rerank — fusion, dedupe, sponsor filter, expansion."""
from shorts_generator import rerank


def _hl(start, end, score):
    return {"title": "t", "start_time": start, "end_time": end, "score": score,
            "hook_sentence": "h", "virality_reason": "r", "transcript_excerpt": ""}


def test_rank_normalize_ties_share_mean_rank():
    # values [10,20,20,5] -> order [3,0,1,2]; ranks 5=0, 10=1, 20,20=(2+3)/2=2.5
    out = rerank.rank_normalize([10, 20, 20, 5])
    assert out[3] == 0.0              # 5 (smallest)
    assert out[0] == 1 / 3            # 10
    assert out[1] == out[2] == 2.5 / 3  # 20,20 tie (avg rank 2.5 / (n-1)=3)


def test_rank_normalize_single_and_empty():
    assert rerank.rank_normalize([]) == []
    assert rerank.rank_normalize([42]) == [1.0]


def test_fuse_attaches_signals_and_score(heatmap, chapters, energy):
    hs = [_hl(0, 10, 50), _hl(20, 30, 90), _hl(40, 50, 30)]
    out = rerank.fuse(hs, heatmap, chapters, energy)
    assert len(out) == 3
    for h in out:
        assert 0 <= h["score"] <= 100
        assert "signals" in h
        assert h["llm_score"] in (50, 90, 30)
        assert "signals_present" in h["signals"]
    # sorted descending by score
    assert out[0]["score"] >= out[-1]["score"]


def test_fuse_missing_signals_renormalize_to_llm_only():
    hs = [_hl(0, 10, 50), _hl(20, 30, 90)]
    out = rerank.fuse(hs, [], [], None)
    # only llm present -> weight renormalizes to 1.0
    assert out[0]["signals"]["signals_present"] == ["llm"]
    assert out[0]["signals"]["weights"]["llm"] == 1.0


def test_fuse_empty_returns_empty():
    assert rerank.fuse([], heatmap=[], chapters=[], energy=None) == []


def test_dedupe_semantic_drops_near_duplicate():
    a = _hl(0, 30, 90)
    a["transcript_excerpt"] = "the big mistake cost me fifty thousand dollars"
    b = _hl(100, 130, 70)
    b["transcript_excerpt"] = "the big mistake cost me fifty thousand dollars today"
    c = _hl(200, 230, 60)
    c["transcript_excerpt"] = "a completely different story about fishing"
    kept = rerank.dedupe_semantic([a, b, c])
    assert len(kept) == 2
    assert kept[0]["score"] == 90  # higher-scoring of the dup pair survives


def test_filter_sponsor_overlaps_drops_inside():
    segs = [{"start": 100.0, "end": 200.0}]
    inside = _hl(110, 190, 90)
    partial = _hl(180, 300, 80)   # 20s of 120s overlap ~17%
    kept = rerank.filter_sponsor_overlaps([inside, partial], segs)
    assert [c["score"] for c in kept] == [80]


def test_filter_sponsor_overlaps_no_segments_passthrough():
    hs = [_hl(0, 10, 50)]
    assert rerank.filter_sponsor_overlaps(hs, []) is hs


def test_expand_for_context_no_segments_returns_unchanged(heatmap, energy):
    hs = [_hl(20, 30, 90)]
    out = rerank.expand_for_context(hs, [], heatmap, energy)
    assert out[0]["start_time"] == 20 and out[0]["end_time"] == 30


def test_expand_for_context_extends_peak_anchored(heatmap, energy):
    # segments must span past the clip+tail for the forward snap to find an edge
    segs = [{"start": float(i), "end": float(i) + 2, "text": str(i)} for i in range(0, 40, 2)]
    hs = [_hl(22, 28, 90)]  # overlaps replay peak at 20-30
    out = rerank.expand_for_context(hs, segs, heatmap, energy)
    assert out[0]["context_expanded"] is True
    assert out[0]["start_time"] <= 22   # lead-in extended backward
    assert out[0]["end_time"] >= 28     # tail extended forward past payoff

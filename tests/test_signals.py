"""Tests for shorts_generator.signals — pure functions, no network."""
from shorts_generator import signals as sig


def test_hms_format():
    assert sig.hms(0) == "00:00"
    assert sig.hms(65) == "01:05"
    assert sig.hms(3723) == "01:02:03"
    assert sig.hms(-5) == "00:00"


def test_content_words_strips_stopwords_and_short():
    words = sig.content_words("The big mistake cost me a lot of money")
    assert "mistake" in words and "money" in words
    assert "the" not in words and "a" not in words and "of" not in words
    assert "me" not in words  # len <= 2 filtered


def test_jaccard_basic():
    assert sig.jaccard(set(), set()) == 0.0
    assert sig.jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert 0 < sig.jaccard({"a", "b"}, {"b", "c"}) < 1


def test_normalize_heatmap_filters_bad_points():
    raw = [
        {"start_time": 0, "end_time": 5, "value": 0.3},
        {"start_time": 5, "end_time": 5, "value": 0.4},  # end<=start dropped
        "junk",
        {"start_time": 5, "end_time": 10, "value": 0.8},
    ]
    out = sig.normalize_heatmap(raw)
    assert len(out) == 2
    assert out[0]["start"] == 0


def test_heatmap_mean_duration_weighted(heatmap):
    # 0-10@0.2, 10-20@0.5, 20-30@1.0 -> over 0-30 mean = (10*0.2+10*0.5+10*1.0)/30 = 17/30
    assert sig.heatmap_mean(heatmap, 0, 30) == (2 + 5 + 10) / 30
    assert sig.heatmap_mean(heatmap, 0, 0) == 0.0
    assert sig.heatmap_mean([], 0, 10) == 0.0


def test_peak_windows_strongest_first(heatmap):
    peaks = sig.peak_windows(heatmap, top_n=3)
    assert peaks[0]["value"] == 1.0
    assert peaks[0]["start"] == 20


def test_sparkline_nonempty(heatmap):
    line = sig.sparkline(heatmap)
    assert len(line) > 0 and all(c in "▁▂▃▄▅▆▇█" for c in line)
    assert sig.sparkline([]) == ""


def test_normalize_chapters_sorts_and_keeps_title():
    out = sig.normalize_chapters([{"start_time": 5, "end_time": 10, "title": "b"}, {"start_time": 0, "title": "a"}])
    assert out[0]["start"] == 0 and out[0]["title"] == "a"
    assert out[1]["end"] == 10


def test_chapter_score_interesting_vs_plain(chapters):
    assert sig.chapter_score(chapters, 20, 30) == 1.0  # "the big mistake" matches
    assert sig.chapter_score(chapters, 0, 10) == 0.5   # "intro" does not match
    assert sig.chapter_score([], 0, 10) is None


def test_audio_score_bounded_and_no_double_count(energy):
    quiet = sig.audio_score(energy, 0, 2)          # no spikes -> 0.7*0.1
    assert quiet == round(0.7 * 0.1, 4)
    with_spikes = sig.audio_score(energy, 0, 7)     # 2 spikes -> 0.7*mean + 0.3*(2/3)
    assert with_spikes <= 1.0
    assert with_spikes > quiet
    capped = sig.audio_score({"values": [1.0] * 10, "spikes": [0, 1, 2, 3]}, 0, 10)
    assert capped == 1.0


def test_audio_score_none_when_no_energy():
    assert sig.audio_score(None, 0, 10) is None
    assert sig.audio_score({"values": []}, 0, 10) is None


def test_pause_boundaries(segments):
    # gap between seg0 (end 2.0) and seg1 (start 2.5) is 0.5 < 1.0 -> no boundary
    # gap between seg1 (end 5.0) and seg2 (start 5.0) is 0 -> none
    bounds = sig.pause_boundaries(segments, min_gap=0.4)
    assert 2.5 in bounds


def test_candidate_boundaries_collects_all(segments, heatmap, energy):
    # default pause min_gap=1.0 -> the fixture's 0.5s gap yields no pause boundary;
    # but replay peaks and audio spikes are collected.
    bounds = sig.candidate_boundaries(segments, heatmap, energy)
    assert 20.0 in bounds  # replay peak
    assert 3.0 in bounds and 6.0 in bounds  # audio spikes


def test_build_hints_contains_peaks(heatmap, chapters, energy):
    h = sig.build_hints(heatmap, chapters, [2.5], energy)
    assert "replay peaks" in h
    assert "the big mistake" in h
    assert "Natural clip boundaries" in h


def test_build_hints_chunk_relative_rebase(heatmap, chapters):
    # peak at abs 20s, chunk offset 15 -> chunk-relative 00:05
    h = sig.build_hints(heatmap, chapters, [], None, offset=15, window=(15, 50))
    assert "00:05" in h
    # abs 0 peak is outside the window -> dropped
    assert "00:00-" not in h


def test_build_hints_empty():
    assert sig.build_hints([], [], [], None) == ""

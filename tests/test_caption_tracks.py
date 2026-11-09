"""Tests for shorts_generator.caption_tracks — original-track selection (no network)."""
from shorts_generator import caption_tracks as ct


def _fmt(url):
    return {"url": url, "ext": "srt"}


def _info(**overrides):
    info = {
        "id": "abc12345678",
        "title": "Sample",
        "language": "en",
        "subtitles": {},
        "automatic_captions": {
            "en": [_fmt("https://example.com/api/timedtext?v=abc&lang=en")],
            "ne": [_fmt("https://example.com/api/timedtext?v=abc&lang=ne&tlang=ne")],
        },
    }
    info.update(overrides)
    return info


def test_base_language_normalizes_codes():
    assert ct.base_language("en-US") == "en"
    assert ct.base_language("NE-orig") == "ne"
    assert ct.base_language(None) == ""
    assert ct.base_language("") == ""


def test_collect_tracks_classifies_kinds():
    tracks = ct.collect_tracks(_info())
    assert set(tracks[ct.KIND_UPLOADED]) == set()
    assert set(tracks[ct.KIND_ORIGINAL]) == {"en"}
    assert set(tracks[ct.KIND_TRANSLATED]) == {"ne"}


def test_translated_request_falls_back_to_original():
    track = ct.choose_track(_info(), langs=["ne"])
    assert track is not None
    assert track["kind"] == ct.KIND_ORIGINAL
    assert track["lang"] == "en"


def test_allow_translated_returns_translation():
    track = ct.choose_track(_info(), langs=["ne"], allow_translated=True)
    assert track is not None
    assert track["kind"] == ct.KIND_TRANSLATED
    assert track["lang"] == "ne"


def test_uploaded_track_wins_for_matching_language():
    info = _info(subtitles={"en": [_fmt("https://example.com/uploaded/en.srt")]})
    track = ct.choose_track(info, langs=["en"])
    assert track is not None
    assert track["kind"] == ct.KIND_UPLOADED
    assert track["lang"] == "en"


def test_video_language_used_when_no_request():
    info = _info(language="ne", automatic_captions={"ne": [_fmt("https://example.com/ne")]})
    track = ct.choose_track(info)
    assert track is not None
    assert track["kind"] == ct.KIND_ORIGINAL
    assert track["lang"] == "ne"


def test_no_captions_returns_none():
    info = _info(subtitles={}, automatic_captions={})
    assert ct.choose_track(info, langs=["ne"]) is None
    assert ct.choose_track(info, langs=["ne"], allow_translated=True) is None


def test_raw_language_code_matches_requested_base():
    info = _info(automatic_captions={"en-US": [_fmt("https://example.com/en-us")]})
    track = ct.choose_track(info, langs=["en"])
    assert track is not None
    assert track["lang"] == "en-US"
    assert track["base_lang"] == "en"


def test_fetch_source_subs_returns_cached_file(tmp_path):
    cached = tmp_path / "source_abc12345678_auto.en.srt"
    cached.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n", encoding="utf-8")
    result = ct.fetch_source_subs("https://youtu.be/abc12345678", str(tmp_path), "abc12345678")
    assert result == str(cached)


def test_cached_caption_respects_requested_language(tmp_path):
    prefix = "source_abc12345678_auto"
    en = tmp_path / f"{prefix}.en.srt"
    ne = tmp_path / f"{prefix}.ne.srt"
    en.write_text("en", encoding="utf-8")
    ne.write_text("ne", encoding="utf-8")
    assert ct._cached_caption(str(tmp_path), prefix, ["en"]).endswith(".en.srt")
    assert ct._cached_caption(str(tmp_path), prefix, ["ne"]).endswith(".ne.srt")
    assert ct._cached_caption(str(tmp_path), prefix, ["fr"]) is None

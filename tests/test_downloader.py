"""Tests for shorts_generator.downloader — URL parsing + format selection (no network)."""
import pytest

from shorts_generator.downloader import (
    _fmt_tag,
    _format_for,
    _normalize_fmt,
    extract_youtube_video_id,
    require_youtube_url,
)


@pytest.mark.parametrize("url,expected", [
    ("https://www.youtube.com/watch?v=6G0bG6qWqTs", "6G0bG6qWqTs"),
    ("https://youtube.com/watch?v=abc123&feature=shared", "abc123"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/shortId123", "shortId123"),
    ("https://www.youtube.com/embed/embedId", "embedId"),
    ("https://www.youtube.com/live/liveId123", "liveId123"),
    ("https://example.com/video", None),
    ("not a url", None),
    ("https://vimeo.com/12345", None),
])
def test_extract_youtube_video_id(url, expected):
    assert extract_youtube_video_id(url) == expected


def test_require_youtube_url_returns_id():
    assert require_youtube_url("https://youtu.be/abc123") == "abc123"


def test_require_youtube_url_raises_on_non_youtube():
    with pytest.raises(RuntimeError, match="YouTube URL required"):
        require_youtube_url("https://vimeo.com/123")


def test_normalize_fmt():
    assert _normalize_fmt(None) == "max"
    assert _normalize_fmt("MAX") == "max"
    assert _normalize_fmt(" 1080 ") == "1080"


def test_format_for_max():
    assert _format_for("max") == "bestvideo*+bestaudio/best"
    assert _format_for("highest") == "bestvideo*+bestaudio/best"


def test_format_for_height_cap():
    sel = _format_for("720")
    assert "height<=720" in sel
    assert sel.startswith("bestvideo[height<=720]+bestaudio/")


def test_format_for_lowest():
    assert _format_for("lowest") == "worstvideo+worstaudio/worst"


def test_fmt_tag():
    assert _fmt_tag("max") == "max"
    assert _fmt_tag("1080") == "1080"
    assert _fmt_tag("lowest") == "low"

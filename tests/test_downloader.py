"""Tests for shorts_generator.downloader — URL parsing + format selection (no network)."""
import json
from pathlib import Path

import pytest

from shorts_generator import downloader
from shorts_generator.downloader import (
    _ensure_netscape_cookiefile,
    _fmt_tag,
    _format_for,
    _normalize_fmt,
    download_audio,
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
    # scheme-less pastes are normalized
    ("youtube.com/watch?v=noScheme1", "noScheme1"),
    ("www.youtube.com/watch?v=noScheme2", "noScheme2"),
    ("youtu.be/noScheme3", "noScheme3"),
    ("www.youtube.com/shorts/noScheme4", "noScheme4"),
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


def test_download_audio_returns_cached_file(tmp_path):
    # A cached <id>.m4a must be returned without touching the network.
    path = tmp_path / "abc12345678.m4a"
    path.write_bytes(b"fake")
    assert download_audio("https://youtu.be/abc12345678", out_dir=str(tmp_path)) == str(path)


def test_download_audio_rejects_non_youtube(tmp_path):
    assert download_audio("https://example.com/video", out_dir=str(tmp_path)) is None


def test_ensure_netscape_cookiefile_converts_json(tmp_path, monkeypatch):
    monkeypatch.setattr(downloader, "OUTPUT_DIR", str(tmp_path))
    cookies = tmp_path / "cookies.json"
    cookies.write_text(
        json.dumps(
            [
                {
                    "domain": ".youtube.com",
                    "name": "SID",
                    "value": "secret",
                    "path": "/",
                    "secure": True,
                    "expirationDate": 4102444800,
                }
            ]
        ),
        encoding="utf-8",
    )
    cache = _ensure_netscape_cookiefile(str(cookies))
    assert Path(cache).name == ".cookies_netscape.txt"
    content = Path(cache).read_text(encoding="utf-8")
    assert "# Netscape HTTP Cookie File" in content
    assert "\tSID\tsecret" in content

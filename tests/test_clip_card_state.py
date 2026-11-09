"""Tests for Studio render-state persistence (no GUI event loop needed)."""
import json

import pytest

pytest.importorskip("PySide6")

from studio_app.clip_card import _persist_clip, _video_assets  # noqa: E402


def test_persist_clip_merges_render_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_OUTPUT_DIR", str(tmp_path))
    video_dir = tmp_path / "vid123"
    video_dir.mkdir()
    clips_path = video_dir / "clips.json"
    clips_path.write_text(json.dumps({
        "video_id": "vid123",
        "clips": [
            {"rank": 1, "title": "one", "short_path": None},
            {"rank": 2, "title": "two"},
        ],
    }), encoding="utf-8")

    _persist_clip("vid123", {
        "rank": 1,
        "short_path": "D:/out/1_one_short.mp4",
        "thumb_path": "D:/out/1_one_short.jpg",
    })

    payload = json.loads(clips_path.read_text(encoding="utf-8"))
    first = payload["clips"][0]
    assert first["short_path"] == "D:/out/1_one_short.mp4"
    assert first["thumb_path"] == "D:/out/1_one_short.jpg"
    assert "short_path" not in payload["clips"][1]


def test_video_assets_prefers_word_srt_and_ignores_clip_srt(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_OUTPUT_DIR", str(tmp_path))
    video_dir = tmp_path / "vid123"
    video_dir.mkdir()
    (video_dir / "source_vid123_max.mp4").write_bytes(b"")
    (video_dir / "source_vid123_max.words.srt").write_text(
        "1\n00:00:01,000 --> 00:00:01,400\nhello\n\n"
        "2\n00:00:01,400 --> 00:00:01,800\nworld\n",
        encoding="utf-8",
    )
    (video_dir / "1_clip_short.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nWRONG\n",
        encoding="utf-8",
    )

    _video_dir, source, segments = _video_assets("vid123")
    assert source.endswith("source_vid123_max.mp4")
    assert segments
    assert segments[0]["word"] == "hello"
    assert all(s.get("text") != "WRONG" for s in segments)

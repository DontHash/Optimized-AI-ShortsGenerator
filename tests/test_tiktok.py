"""Tests for shorts_generator.tiktok — ID parsing, format selection, queue, pacing."""
import time

import shorts_generator.tiktok as tiktok_mod
from shorts_generator.tiktok import (
    _TIKTOK_PLACEHOLDER_TITLE_RE,
    extract_tiktok_id,
    process_tiktok_queue,
    watermark_free_format,
)


def test_extract_tiktok_id_variants():
    assert extract_tiktok_id("https://www.tiktok.com/@user/video/1234567890") == "1234567890"
    assert extract_tiktok_id("https://www.tiktok.com/@user.name/video/9876543210") == "9876543210"
    assert extract_tiktok_id("vm.tiktok.com/abc123/") is None  # short links unsupported
    assert extract_tiktok_id("https://youtu.be/abc123") is None
    assert extract_tiktok_id("not a url") is None
    assert extract_tiktok_id("") is None
    # scheme-less pastes are normalized
    assert extract_tiktok_id("www.tiktok.com/@user/video/555444333") == "555444333"
    assert extract_tiktok_id("tiktok.com/@user/video/555444334") == "555444334"


def test_watermark_free_format_excludes_download():
    sel = watermark_free_format()
    assert 'format_id!="download"' in sel  # watermarked format excluded
    assert sel.startswith("bv*+ba/")  # best video+audio preferred


def test_process_tiktok_queue_parallel_and_callbacks(monkeypatch):
    def fake(url, out_root=None, use_cookies=False):
        time.sleep(0.1)
        return {"ok": True, "url": url, "video_id": "v1", "title": "t", "author": "a",
                "duration": 5, "stats": {}, "thumbnail_path": None, "source_path": "x.mp4",
                "clips_json": "y"}
    monkeypatch.setattr(tiktok_mod, "download_tiktok", fake)
    done = []
    report = process_tiktok_queue(
        ["u1", "u2", "u3", "u4"], out_root="output", workers=4, on_video_done=done.append
    )
    assert len(report["ok"]) == 4
    assert len(done) == 4


def test_process_tiktok_queue_fault_isolation(monkeypatch, tmp_path):
    def flaky(url, out_root=None, use_cookies=False):
        if "bad" in url:
            return {"ok": False, "url": url, "error": "boom"}
        return {"ok": True, "url": url, "video_id": "v", "title": "t", "author": "a",
                "duration": 0, "stats": {}, "thumbnail_path": None, "source_path": "",
                "clips_json": ""}
    monkeypatch.setattr(tiktok_mod, "download_tiktok", flaky)
    report = process_tiktok_queue(
        ["good1", "bad1", "good2"], out_root=str(tmp_path), workers=2
    )
    assert len(report["ok"]) == 2
    assert len(report["failed"]) == 1
    assert report["failed"][0]["error"] == "boom"


def test_process_tiktok_queue_cancel(monkeypatch, tmp_path):
    monkeypatch.setattr(tiktok_mod, "download_tiktok",
                        lambda url, out_root=None, use_cookies=False: {"ok": True, "url": url})
    report = process_tiktok_queue(["u1", "u2"], out_root=str(tmp_path), is_cancelled=lambda: True)
    assert report.get("cancelled") is True


def test_process_tiktok_queue_delay_staggers_starts(monkeypatch, tmp_path):
    """With delay, video i starts at ~delay*i -> total wall time grows with delay."""
    starts = []

    def tracked(url, out_root=None, use_cookies=False):
        starts.append(time.monotonic())
        return {"ok": True, "url": url, "video_id": url}
    monkeypatch.setattr(tiktok_mod, "download_tiktok", tracked)

    process_tiktok_queue(["u1", "u2", "u3"], out_root=str(tmp_path), workers=3, delay=0.15)
    # u2 starts >= 0.15s after u1, u3 >= 0.30s after u1
    assert len(starts) == 3
    assert starts[1] - starts[0] >= 0.13
    assert starts[2] - starts[0] >= 0.28


def test_placeholder_title_regex():
    assert _TIKTOK_PLACEHOLDER_TITLE_RE.match("TikTok video #1234567890")
    assert not _TIKTOK_PLACEHOLDER_TITLE_RE.match("real caption here")
    assert not _TIKTOK_PLACEHOLDER_TITLE_RE.match("TikTok video")

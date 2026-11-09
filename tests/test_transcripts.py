"""Tests for shorts_generator.transcripts — YouTube-caption fetching (no network)."""
from pathlib import Path

from shorts_generator import transcripts as tr

SAMPLE_SRT = """1
00:00:01,000 --> 00:00:03,500
Hello world.

2
00:00:03,600 --> 00:00:06,000
Second line.
"""

VIDEO_ID = "abc12345678"


def test_srt_to_text_strips_timestamps(tmp_path):
    path = tmp_path / "x.srt"
    path.write_text(SAMPLE_SRT, encoding="utf-8")
    assert tr._srt_to_text(str(path)) == "Hello world.\nSecond line."


def test_download_transcripts_writes_srt_and_txt(tmp_path, monkeypatch):
    out = tmp_path / "out"

    def fake_fetch(video_url, out_dir, video_id, language=None, langs=None):
        path = Path(out_dir) / f"source_{video_id}_auto.en.srt"
        path.write_text(SAMPLE_SRT, encoding="utf-8")
        return str(path)

    monkeypatch.setattr(tr, "fetch_auto_subs", fake_fetch)
    report = tr.download_transcripts([f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out))

    assert len(report["ok"]) == 1
    assert not report["failed"]
    srt = out / f"{VIDEO_ID}.en.srt"
    txt = out / f"{VIDEO_ID}.en.txt"
    assert srt.is_file()
    assert txt.read_text(encoding="utf-8") == "Hello world.\nSecond line."
    assert (out / "transcripts_report.json").is_file()


def test_no_captions_fails_without_whisper_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "fetch_auto_subs", lambda *a, **k: None)
    report = tr.download_transcripts(
        [f"https://www.youtube.com/watch?v={VIDEO_ID}"], out_dir=str(tmp_path)
    )
    assert not report["ok"]
    assert "Whisper" in report["failed"][0]["error"]


def test_invalid_url_fails_before_network(tmp_path, monkeypatch):
    calls = []

    def fake_fetch(*a, **k):
        calls.append(1)

    monkeypatch.setattr(tr, "fetch_auto_subs", fake_fetch)
    report = tr.download_transcripts(["https://example.com/video"], out_dir=str(tmp_path))
    assert report["failed"][0]["error"] == "not a YouTube URL"
    assert not calls


def test_cached_srt_skips_network_and_backfills_txt(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / f"{VIDEO_ID}.en.srt").write_text(SAMPLE_SRT, encoding="utf-8")

    def boom(*a, **k):
        raise AssertionError("network fetch should not run on cache hit")

    monkeypatch.setattr(tr, "fetch_auto_subs", boom)
    report = tr.download_transcripts([f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out))
    assert report["ok"][0]["cached"] is True
    assert (out / f"{VIDEO_ID}.en.txt").is_file()


def test_cache_is_per_language(tmp_path, monkeypatch):
    out = tmp_path / "out"
    out.mkdir()
    (out / f"{VIDEO_ID}.ne.srt").write_text(SAMPLE_SRT, encoding="utf-8")
    calls = []

    def fake_fetch(video_url, out_dir, video_id, language=None, langs=None):
        calls.append(langs)
        path = Path(out_dir) / f"source_{video_id}_auto.en.srt"
        path.write_text(SAMPLE_SRT, encoding="utf-8")
        return str(path)

    monkeypatch.setattr(tr, "fetch_auto_subs", fake_fetch)
    report = tr.download_transcripts(
        [f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out), langs=["en"]
    )
    assert calls == [["en"]]
    assert report["ok"][0]["cached"] is False
    assert (out / f"{VIDEO_ID}.en.srt").is_file()


def test_audio_only_skips_captions(tmp_path, monkeypatch):
    out = tmp_path / "out"

    def boom(*a, **k):
        raise AssertionError("captions must not be fetched with audio_only")

    def fake_audio(video_url, out_dir, video_id):
        path = Path(out_dir) / f"{video_id}.m4a"
        path.write_bytes(b"\x00")
        return str(path)

    monkeypatch.setattr(tr, "fetch_auto_subs", boom)
    monkeypatch.setattr(tr, "download_audio", fake_audio)
    report = tr.download_transcripts(
        [f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out), audio_only=True
    )
    assert report["ok"][0]["audio"].endswith(f"{VIDEO_ID}.m4a")
    assert report["ok"][0]["srt"] == ""


def test_audio_failure_marks_entry_failed_with_partial_srt(tmp_path, monkeypatch):
    out = tmp_path / "out"

    def fake_fetch(video_url, out_dir, video_id, language=None, langs=None):
        path = Path(out_dir) / f"source_{video_id}_auto.en.srt"
        path.write_text(SAMPLE_SRT, encoding="utf-8")
        return str(path)

    monkeypatch.setattr(tr, "fetch_auto_subs", fake_fetch)
    monkeypatch.setattr(tr, "download_audio", lambda *a, **k: None)
    report = tr.download_transcripts(
        [f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out), audio=True
    )
    assert not report["ok"]
    entry = report["failed"][0]
    assert entry["srt"].endswith(f"{VIDEO_ID}.en.srt")
    assert "audio" in entry["error"]


NEPALI_SRT = """1
00:00:01,000 --> 00:00:03,500
नमस्ते संसार।

2
00:00:03,600 --> 00:00:06,000
नेपाली भाषा।
"""


def test_nepali_devanagari_langs_roundtrip(tmp_path, monkeypatch):
    out = tmp_path / "out"
    captured = {}

    def fake_fetch(video_url, out_dir, video_id, language=None, langs=None):
        captured["langs"] = langs
        path = Path(out_dir) / f"source_{video_id}_auto.ne.srt"
        path.write_text(NEPALI_SRT, encoding="utf-8")
        return str(path)

    monkeypatch.setattr(tr, "fetch_auto_subs", fake_fetch)
    report = tr.download_transcripts(
        [f"https://youtu.be/{VIDEO_ID}"], out_dir=str(out), langs=["ne"]
    )
    assert captured["langs"] == ["ne"]
    assert report["ok"][0]["srt"].endswith(f"{VIDEO_ID}.ne.srt")
    assert (out / f"{VIDEO_ID}.ne.txt").read_text(encoding="utf-8") == "नमस्ते संसार।\nनेपाली भाषा।"

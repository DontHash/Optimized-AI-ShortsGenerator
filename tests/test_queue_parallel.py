"""Tests for shorts_generator.queue.process_queue — parallel workers, callbacks, cancel."""
import time

import shorts_generator.queue as queue_mod
from shorts_generator.queue import process_queue


def _fake_find_clips(ok: bool = True, delay: float = 0.0, **kwargs):
    def run(youtube_url, **ignored):
        if delay:
            time.sleep(delay)
        if not ok:
            raise RuntimeError(f"boom {youtube_url}")
        return {"video_id": youtube_url.rsplit("/", 1)[-1], "clips": [{"rank": 1}],
                "clips_json": "out/x/clips.json"}
    return run


def test_sequential_workers_reports_ok(monkeypatch):
    monkeypatch.setattr(queue_mod, "find_clips", _fake_find_clips())
    report = process_queue(["https://youtu.be/a", "https://youtu.be/b"], out_root="output")
    assert len(report["ok"]) == 2 and not report["failed"]


def test_parallel_workers_fault_isolation(monkeypatch, tmp_path):
    def flaky(youtube_url, **ignored):
        if "bad" in youtube_url:
            raise RuntimeError(f"boom {youtube_url}")
        return {"video_id": "good", "clips": [], "clips_json": "x"}
    monkeypatch.setattr(queue_mod, "find_clips", flaky)
    report = process_queue(
        ["https://youtu.be/good1", "https://youtu.be/bad1", "https://youtu.be/good2"],
        out_root=str(tmp_path), workers=2,
    )
    assert len(report["ok"]) == 2
    assert len(report["failed"]) == 1
    assert "boom" in report["failed"][0]["error"]


def test_parallel_workers_actually_run_concurrently(monkeypatch):
    calls = {"n": 0}
    orig = time.monotonic

    def slow(youtube_url, **ignored):
        calls["n"] += 1
        time.sleep(0.4)
        return {"video_id": "v", "clips": [], "clips_json": "x"}

    monkeypatch.setattr(queue_mod, "find_clips", slow)
    start = orig()
    process_queue(["u1", "u2", "u3", "u4"], out_root="output", workers=4)
    elapsed = orig() - start
    # 4 x 0.4s sleeps at 4 workers -> ~0.4-0.8s, not 1.6s
    assert elapsed < 1.3, f"not concurrent: {elapsed:.2f}s"


def test_on_video_done_callback_called(monkeypatch):
    done = []
    monkeypatch.setattr(queue_mod, "find_clips", _fake_find_clips(delay=0.05))
    process_queue(
        ["https://youtu.be/a", "https://youtu.be/b"],
        out_root="output", workers=2,
        on_video_done=done.append,
    )
    assert len(done) == 2
    assert all(d.get("ok") for d in done)


def test_is_cancelled_stops_queue(monkeypatch):
    monkeypatch.setattr(queue_mod, "find_clips", _fake_find_clips(delay=0.2))
    report = process_queue(
        ["u1", "u2", "u3", "u4"],
        out_root="output", workers=2,
        is_cancelled=lambda: True,
    )
    assert report.get("cancelled") is True
    # cancellation flag checked before first batch -> nothing completed
    assert not report["ok"] and not report["failed"]

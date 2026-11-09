"""End-to-end 9:16 render smoke test (skipped when ffmpeg is unavailable)."""
import json
import os
import shutil
import subprocess

import pytest

from shorts_generator.clipper import render_shorts

pytestmark = pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg/ffprobe not on PATH",
)


def _probe(path: str) -> dict:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=width,height,codec_type,sample_rate:format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def test_render_short_clamps_duration_and_is_vertical(tmp_path):
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=8",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-c:a", "aac", str(source),
        ],
        check=True,
    )

    clip = {
        "rank": 1,
        "name": "render-test",
        "title": "Render test",
        "start_time": 2.0,
        "end_time": 6.0,
    }
    segments = [
        {"start": 2.0, "end": 4.0, "text": "hello world"},
        {"start": 4.0, "end": 6.0, "text": "second caption"},
    ]
    result = render_shorts(str(source), clip, str(tmp_path), segments)

    assert result.get("short_path"), result.get("error")
    assert os.path.isfile(result["short_path"])
    info = _probe(result["short_path"])
    streams = info.get("streams", [])
    video = next(s for s in streams if s.get("codec_type") == "video")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    assert video["height"] > video["width"]  # vertical
    assert 3.5 <= float(info["format"]["duration"]) <= 4.5
    if audio:
        assert audio.get("sample_rate") == "48000"
    assert result.get("thumb_path") and os.path.isfile(result["thumb_path"])

    if result.get("ass_path"):
        ass = open(result["ass_path"], encoding="utf-8").read()
        assert "PlayResX: 1080" in ass
        assert "PlayResY: 1920" in ass

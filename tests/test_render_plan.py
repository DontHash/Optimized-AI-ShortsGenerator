"""Tests for the single-pass render plan and filter graph (no ffmpeg needed)."""
import pytest

from shorts_generator.render import RenderPlan, RenderSegment, build_filter_graph
from shorts_generator.render.encoder import choose_encoder, video_args


def _plan(tmp_path, **overrides):
    ass = tmp_path / "captions.ass"
    ass.write_text("[Script Info]\n", encoding="utf-8")
    crop = {"x": 100, "y": 0, "w": 607, "h": 1080}
    values = {
        "source": "source.mp4",
        "output": "out.mp4",
        "segments": [
            RenderSegment(start=10.0, end=12.0, crop=crop),
            RenderSegment(start=14.0, end=17.0, crop=crop),
        ],
        "width": 540,
        "height": 960,
        "fps": 30,
        "crf": 20,
        "encoder": "libx264",
        "ass_path": str(ass),
        "fade": 0.5,
        "hdr": False,
        "audio": True,
    }
    values.update(overrides)
    return RenderPlan(**values)


def test_filter_graph_has_one_concat_pipeline(tmp_path):
    graph, vlabel, alabel, total = build_filter_graph(_plan(tmp_path))
    assert vlabel == "[vout]"
    assert alabel == "[aout]"
    assert total == pytest.approx(5.0)
    assert "split=2[v0][v1]" in graph
    assert "trim=start=0.000:end=2.000" in graph
    assert "trim=start=4.000:end=7.000" in graph  # relative to first_start=10
    assert "crop=607:1080:100:0" in graph
    assert "concat=n=2:v=1:a=0[vbase]" in graph
    assert "asplit=2[a0][a1]" in graph
    assert "concat=n=2:v=0:a=1[abase]" in graph
    assert "loudnorm=I=-14.0" in graph
    assert "ass='" in graph
    assert "format=yuv420p[vout]" in graph


def test_filter_graph_single_segment_without_audio_or_captions(tmp_path):
    plan = _plan(
        tmp_path,
        segments=[RenderSegment(start=10.0, end=12.0, crop={"x": 0, "y": 0, "w": 607, "h": 1080})],
        audio=False,
        ass_path="",
        fade=0.0,
    )
    graph, vlabel, alabel, total = build_filter_graph(plan)
    assert vlabel == "[vout]"
    assert alabel is None
    assert total == pytest.approx(2.0)
    assert "split=" not in graph
    assert "[0:a]" not in graph
    assert "loudnorm" not in graph
    assert "ass=" not in graph
    assert "fade=" not in graph
    assert "format=yuv420p[vout]" in graph


def test_encoder_args_cover_hardware_and_fallback():
    assert video_args("libx264", 20)[:4] == ["-c:v", "libx264", "-preset", "fast"]
    assert video_args("h264_nvenc", 20)[:2] == ["-c:v", "h264_nvenc"]
    assert video_args("h264_qsv", 20)[:2] == ["-c:v", "h264_qsv"]
    assert video_args("h264_amf", 20)[:2] == ["-c:v", "h264_amf"]
    assert video_args("h264_videotoolbox", 20)[:2] == ["-c:v", "h264_videotoolbox"]


def test_choose_encoder_respects_explicit_choice(monkeypatch):
    monkeypatch.setattr(
        "shorts_generator.render.encoder.available_encoders",
        lambda: {"h264_nvenc"},
    )
    assert choose_encoder("libx264") == "libx264"
    assert choose_encoder("auto") == "h264_nvenc"

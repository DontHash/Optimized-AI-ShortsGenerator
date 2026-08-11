"""Tests for studio_app.settings_panel .env parsing (GUI-only; skipped without PySide6)."""
import pytest

pytest.importorskip("PySide6")

import studio_app.settings_panel as sp  # noqa: E402

SAMPLE = """# comment
LLM_PROVIDER=gemini
LOCAL_WHISPER_DEVICE=auto     # auto / cpu / cuda
PEAK_LEAD_SECONDS=5           # minimum lead-in before a peak
GEMINI_API_KEY="AQ.some-quoted-value"
RERANK_WEIGHTS=llm:0.45,replay:0.25
"""


def test_load_env_file_strips_inline_comments(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text(SAMPLE, encoding="utf-8")
    monkeypatch.setattr(sp, "_ENV_PATH", env)
    values = sp.load_env_file()
    assert values["LLM_PROVIDER"] == "gemini"
    assert values["LOCAL_WHISPER_DEVICE"] == "auto"
    assert values["PEAK_LEAD_SECONDS"] == "5"
    assert values["GEMINI_API_KEY"] == "AQ.some-quoted-value"
    assert values["RERANK_WEIGHTS"] == "llm:0.45,replay:0.25"


def test_save_env_file_skips_gui_only_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    monkeypatch.setattr(sp, "_ENV_PATH", env)
    n = sp.save_env_file({"_NUM_CLIPS": "3", "A": "2"})
    assert n == 1
    content = env.read_text(encoding="utf-8")
    assert "_NUM_CLIPS" not in content
    assert "A=2" in content

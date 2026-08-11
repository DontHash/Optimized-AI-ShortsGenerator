"""Settings panel: edit .env knobs, persist to disk, apply to the process env."""
import os
import re
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_ENV_PATH = _PROJECT_ROOT / ".env"

_FIELDS = [
    ("llm_provider", "LLM provider", "LLM_PROVIDER", "gemini", "combo", ["gemini", "openai"]),
    ("gemini_key", "Gemini API key", "GEMINI_API_KEY", "", "password", None),
    ("openai_key", "OpenAI API key", "OPENAI_API_KEY", "", "password", None),
    ("whisper_model", "Whisper model", "LOCAL_WHISPER_MODEL", "base", "combo",
     ["tiny", "base", "small", "medium", "large-v3"]),
    ("download_format", "Download quality", "DOWNLOAD_FORMAT", "max", "combo",
     ["max", "1080", "720", "480", "360"]),
    ("auto_subs", "YouTube auto-captions", "AUTO_SUBS", "true", "check", None),
    ("sponsorblock", "SponsorBlock exclusion", "SPONSORBLOCK", "true", "check", None),
    ("cookies_browser", "Browser cookies", "YTDLP_COOKIES_FROM_BROWSER", "edge", "combo",
     ["edge", "chrome", "firefox", "brave", "none"]),
    ("rerank_weights", "Rerank weights", "RERANK_WEIGHTS",
     "llm:0.45,replay:0.25,audio:0.20,chapter:0.10", "line", None),
    ("num_clips", "Default clips per video", "_NUM_CLIPS", "3", "spin", None),
    ("tiktok_delay", "TikTok pacing (s)", "_TIKTOK_DELAY", "8", "spin", None),
    ("shorts_captions", "Shorts: burn captions", "SHORTS_CAPTIONS", "true", "check", None),
    ("shorts_face", "Shorts: face-aware crop", "SHORTS_FACE_CROP", "true", "check", None),
    ("shorts_fade", "Shorts: fade (s)", "_SHORTS_FADE", "1", "spin", None),
]


def _clean_value(raw: str) -> str:
    """Strip quotes and inline comments (a '#' preceded by whitespace) from a .env value."""
    return re.sub(r"\s+#.*$", "", raw.strip().strip('"').strip("'")).strip()


def load_env_file() -> dict:
    """Parse .env into {KEY: value} preserving only the last value per key."""
    values = {}
    if _ENV_PATH.is_file():
        try:
            for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                values[key.strip()] = _clean_value(value)
        except OSError:
            pass
    return values


def save_env_file(overrides: dict) -> int:
    """Rewrite .env, updating the given keys in place; keeps comments/other lines. Returns keys changed.

    Keys starting with "_" are GUI-only controls and are never persisted.
    """
    overrides = {k: v for k, v in overrides.items() if not k.startswith("_")}
    lines = []
    if _ENV_PATH.is_file():
        try:
            lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
    written = set()
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in overrides:
                out.append(f"{key}={overrides[key]}")
                written.add(key)
                continue
        out.append(line)
    for key, value in overrides.items():
        if key not in written:
            out.append(f"{key}={value}")
    _ENV_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
    return len(overrides)


class SettingsPanel(QWidget):
    """Form over the project's .env. Values apply immediately and on save."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self._env = load_env_file()
        self._controls = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(12)

        title = QLabel("Settings")
        title.setObjectName("h1")
        lay.addWidget(title)
        sub = QLabel("Stored in .env — same knobs the CLI uses.")
        sub.setObjectName("dim")
        lay.addWidget(sub)

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignRight)
        for key, label, env_key, default, kind, options in _FIELDS:
            current = self._env.get(env_key, default)
            if kind == "combo":
                ctrl = QComboBox()
                ctrl.addItems(options)
                ctrl.setCurrentText(current if current in options else default)
            elif kind == "check":
                ctrl = QCheckBox()
                ctrl.setChecked(str(current).lower() not in ("false", "0", "off", "none"))
            elif kind == "spin":
                ctrl = QSpinBox()
                if key == "tiktok_delay":
                    ctrl.setRange(0, 120)
                elif key == "shorts_fade":
                    ctrl.setRange(0, 5)
                else:
                    ctrl.setRange(1, 20)
                ctrl.setValue(int(current) if str(current).isdigit() else int(default))
            elif kind == "password":
                ctrl = QLineEdit(current if current and current != default else "")
                ctrl.setEchoMode(QLineEdit.Password)
                ctrl.setPlaceholderText(default)
            else:
                ctrl = QLineEdit(current)
            self._controls[key] = (ctrl, env_key, kind)
            form.addRow(QLabel(label), ctrl)
        lay.addLayout(form)

        row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save)
        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self._reload)
        row.addWidget(save_btn)
        row.addWidget(reload_btn)
        row.addStretch(1)
        lay.addLayout(row)

        self._status = QLabel("")
        self._status.setObjectName("dim")
        lay.addWidget(self._status)
        lay.addStretch(1)

    def _values(self) -> dict:
        overrides = {}
        for ctrl, env_key, kind in self._controls.values():
            if kind == "combo":
                overrides[env_key] = ctrl.currentText()
            elif kind == "check":
                overrides[env_key] = "true" if ctrl.isChecked() else "false"
            elif kind == "spin":
                overrides[env_key] = str(ctrl.value())
            else:
                value = ctrl.text().strip()
                if value:
                    overrides[env_key] = value
        return overrides

    def _save(self):
        overrides = self._values()
        try:
            n = save_env_file(overrides)
        except OSError as e:
            self._status.setText(f"Could not write .env: {e}")
            return
        for key, value in overrides.items():
            os.environ[key] = value
        self._env.update(overrides)
        self._status.setText(f"Saved {n} settings to .env (applies to the next run).")
        self.changed.emit()

    def _reload(self):
        self._env = load_env_file()
        self._status.setText("")
        self.changed.emit()

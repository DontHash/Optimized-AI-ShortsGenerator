"""Face-swap ONNX model download + verification.

Downloads on first use into ``<project>/models/faceswap`` (override with the
``FACESWAP_MODELS_DIR`` env var). Files:

- ``det_10g.onnx``    — SCRFD face detection (bbox + 5 landmarks)
- ``w600k_r50.onnx``  — ArcFace embedding of the reference face
- ``inswapper_128.onnx`` — the actual face swap model

Together ~850 MB. All three come from the official deepinsight/insightface
GitHub releases.
"""
import os
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

BUFFALO_L_ZIP = "https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip"
INSWAPPER_URL = "https://github.com/deepinsight/insightface/releases/download/v0.7/inswapper_128.onnx"

# file name -> (download source, zip member path or None for direct download)
REQUIRED = {
    "det_10g.onnx": (BUFFALO_L_ZIP, "det_10g.onnx"),
    "w600k_r50.onnx": (BUFFALO_L_ZIP, "w600k_r50.onnx"),
    "inswapper_128.onnx": (INSWAPPER_URL, None),
}

_MIN_BYTES = {
    "det_10g.onnx": 5 * 1024 * 1024,
    "w600k_r50.onnx": 50 * 1024 * 1024,
    "inswapper_128.onnx": 200 * 1024 * 1024,
}

ProgressCb = Callable[[str, int, int], None]  # (label, done_bytes, total_bytes)


def model_dir() -> Path:
    override = os.getenv("FACESWAP_MODELS_DIR")
    return Path(override) if override else _PROJECT_ROOT / "models" / "faceswap"


def is_available() -> bool:
    directory = model_dir()
    return all((directory / name).is_file() for name in REQUIRED)


def _fetch(url: str, dest: Path, progress_cb: ProgressCb | None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "clipclipper/0.1"})
    with urllib.request.urlopen(req) as resp, open(tmp, "wb") as out:  # noqa: SIM117
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(dest.name, done, total)
    tmp.replace(dest)


def ensure_models(progress_cb: ProgressCb | None = None, force: bool = False) -> dict:
    """Download any missing model files; returns {name: Path}."""
    directory = model_dir()
    directory.mkdir(parents=True, exist_ok=True)
    result: dict = {}
    for name, (source, member) in REQUIRED.items():
        path = directory / name
        if not force and path.is_file() and path.stat().st_size > _MIN_BYTES[name]:
            result[name] = path
            continue
        if progress_cb:
            progress_cb(name, 0, 0)
        if member is not None:
            with tempfile.TemporaryDirectory(prefix="clipclipper_models_") as tmp:
                archive = Path(tmp) / "buffalo_l.zip"
                _fetch(source, archive, progress_cb)
                with zipfile.ZipFile(archive) as zf:
                    zf.extract(member, tmp)
                shutil.move(Path(tmp) / member, path)
        else:
            _fetch(source, path, progress_cb)
        result[name] = path
    return result

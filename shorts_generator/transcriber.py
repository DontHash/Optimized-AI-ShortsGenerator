"""Transcription via faster-whisper. Caches segment-level SRT by default."""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from .config import (
    LOCAL_WHISPER_DEVICE,
    LOCAL_WHISPER_MODEL,
    LOCAL_WHISPER_VAD_FILTER,
    LOCAL_WHISPER_VAD_PARAMETERS,
    OUTPUT_DIR,
)


def _default_cache_path(media_path: str, word_level: bool = False) -> Path:
    return Path(OUTPUT_DIR) / (Path(media_path).stem + (".words.srt" if word_level else ".srt"))


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, millis = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds + (millis / 1000.0)


def _write_srt(path: Path, transcript: Dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for idx, segment in enumerate(transcript.get("segments", []), start=1):
        start = format_srt_timestamp(float(segment["start"]))
        end = format_srt_timestamp(float(segment["end"]))
        text = str(segment.get("text", "")).strip().replace("\r", "").replace("\n", " ")
        lines.append(str(idx))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _load_srt_cache(cache_path: Path) -> Dict:
    content = cache_path.read_text(encoding="utf-8-sig").strip()
    if not content:
        return {"duration": 0.0, "segments": []}

    segments = []
    for block in re.split(r"\n\s*\n", content):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
            lines = lines[1:]
        if not lines or "-->" not in lines[0]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[0].split("-->", 1)]
        text = "\n".join(lines[1:]).strip()
        segments.append(
            {
                "start": _parse_srt_timestamp(start_raw),
                "end": _parse_srt_timestamp(end_raw),
                "text": text,
            }
        )

    duration = segments[-1]["end"] if segments else 0.0
    return {"duration": duration, "segments": segments}


def _resolve_device() -> str:
    if LOCAL_WHISPER_DEVICE != "auto":
        return LOCAL_WHISPER_DEVICE
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            torch.zeros(1, device="cuda")
            return "cuda"
    except (ImportError, OSError, RuntimeError):
        pass
    return "cpu"


def _load_model():
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper is required. Install it with:\n    pip install -r requirements.txt"
        ) from e

    device = _resolve_device()
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"[transcribe] faster-whisper model={LOCAL_WHISPER_MODEL} device={device}", flush=True)
    return WhisperModel(LOCAL_WHISPER_MODEL, device=device, compute_type=compute_type)


def transcribe(
    media_path: str,
    language: Optional[str] = None,
    word_timestamps: bool = False,
    cache_dir: Optional[str] = None,
) -> Dict:
    """Run faster-whisper. Returns {duration, segments[, words]}."""
    if cache_dir:
        cache_path = Path(cache_dir) / (
            Path(media_path).stem + (".words.srt" if word_timestamps else ".srt")
        )
    else:
        cache_path = _default_cache_path(media_path, word_level=word_timestamps)

    if not word_timestamps and cache_path.exists():
        source_mtime = os.path.getmtime(media_path)
        if cache_path.stat().st_mtime >= source_mtime:
            print(f"[transcribe] reusing cached transcript: {cache_path}", flush=True)
            cached = _load_srt_cache(cache_path)
            if cached["segments"] and cached["duration"] > 0.0:
                print(
                    f"[transcribe] {len(cached['segments'])} cached segments, "
                    f"{cached['duration']:.0f}s",
                    flush=True,
                )
                return cached
            cache_path.unlink(missing_ok=True)

    model = _load_model()
    kwargs = {
        "audio": media_path,
        "language": language,
        "beam_size": 5,
        "condition_on_previous_text": False,
        "word_timestamps": word_timestamps,
        "vad_filter": LOCAL_WHISPER_VAD_FILTER,
    }
    if LOCAL_WHISPER_VAD_FILTER:
        kwargs["vad_parameters"] = LOCAL_WHISPER_VAD_PARAMETERS

    segments_iter, info = model.transcribe(**kwargs)

    segments: List[Dict] = []
    words: List[Dict] = []
    for s in segments_iter:
        segments.append({
            "start": float(s.start),
            "end": float(s.end),
            "text": (s.text or "").strip(),
        })
        if word_timestamps and getattr(s, "words", None):
            for w in s.words:
                if w.word is None:
                    continue
                words.append({
                    "start": float(w.start) if w.start is not None else float(s.start),
                    "end": float(w.end) if w.end is not None else float(s.end),
                    "word": w.word.strip(),
                })

    duration = float(getattr(info, "duration", 0.0)) or (segments[-1]["end"] if segments else 0.0)
    print(f"[transcribe] {len(segments)} segments, {duration:.0f}s of audio", flush=True)

    transcript: Dict = {"duration": duration, "segments": segments}
    if word_timestamps:
        transcript["words"] = words
        print(f"[transcribe] {len(words)} word timestamps", flush=True)
    else:
        _write_srt(cache_path, transcript)
        print(f"[transcribe] wrote cache: {cache_path}", flush=True)

    return transcript

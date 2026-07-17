"""Shorts-style captions from a local video file. Independent of the clip pipeline."""
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import (
    CAPTION_FONT,
    CAPTION_FONT_SIZE,
    CAPTION_HIGHLIGHT_COLOR,
    CAPTION_MAX_WORDS,
)
from .transcriber import format_srt_timestamp, transcribe


def _ass_timestamp(seconds: float) -> str:
    """ASS uses H:MM:SS.cc (centiseconds)."""
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int(round((s - int(s)) * 100))
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _chunk_words(words: List[Dict], max_words: int) -> List[List[Dict]]:
    chunks: List[List[Dict]] = []
    buf: List[Dict] = []
    for w in words:
        if not w.get("word"):
            continue
        buf.append(w)
        if len(buf) >= max_words:
            chunks.append(buf)
            buf = []
    if buf:
        chunks.append(buf)
    return chunks


def write_srt(words: List[Dict], out_path: str, max_words: int = CAPTION_MAX_WORDS) -> str:
    chunks = _chunk_words(words, max_words)
    lines = []
    for i, chunk in enumerate(chunks, 1):
        start = float(chunk[0]["start"])
        end = float(chunk[-1]["end"])
        text = " ".join(w["word"] for w in chunk)
        lines.append(str(i))
        lines.append(f"{format_srt_timestamp(start)} --> {format_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path


def write_ass(
    words: List[Dict],
    out_path: str,
    max_words: int = CAPTION_MAX_WORDS,
    font: str = CAPTION_FONT,
    font_size: int = CAPTION_FONT_SIZE,
    highlight: str = CAPTION_HIGHLIGHT_COLOR,
) -> str:
    """Karaoke-style ASS: 2–4 words/line, current word highlighted."""
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},&H00FFFFFF,{highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3,0,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    chunks = _chunk_words(words, max_words)
    events = []
    for chunk in chunks:
        # One dialogue event per word within the chunk window, highlighting the active word
        chunk_start = float(chunk[0]["start"])
        chunk_end = float(chunk[-1]["end"])
        for i, w in enumerate(chunk):
            w_start = float(w["start"])
            w_end = float(w["end"]) if i < len(chunk) - 1 else chunk_end
            # Clamp to chunk
            w_start = max(w_start, chunk_start)
            w_end = min(w_end, chunk_end)
            if w_end <= w_start:
                continue
            parts = []
            for j, other in enumerate(chunk):
                token = other["word"]
                if j == i:
                    parts.append(r"{\c" + highlight + "}" + token + r"{\c&H00FFFFFF&}")
                else:
                    parts.append(token)
            text = " ".join(parts)
            events.append(
                f"Dialogue: 0,{_ass_timestamp(w_start)},{_ass_timestamp(w_end)},Default,,0,0,0,,{text}"
            )

    Path(out_path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return out_path


def burn_subtitles(video_path: str, ass_path: str, out_path: str) -> str:
    # Escape path for ffmpeg subtitles filter (Windows-friendly: forward slashes + escape colon)
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"ass='{ass_escaped}'",
        "-c:a", "copy",
        out_path,
    ]
    subprocess.run(cmd, check=True)
    return out_path


def generate_captions(
    video_path: str,
    language: Optional[str] = None,
    burn: bool = False,
    out_dir: Optional[str] = None,
) -> Dict[str, str]:
    """Transcribe with word timestamps → .srt + .ass (+ optional burned mp4)."""
    video_path = str(Path(video_path).expanduser().resolve())
    if not os.path.isfile(video_path):
        raise RuntimeError(f"Video not found: {video_path}")

    out_dir = out_dir or str(Path(video_path).parent)
    os.makedirs(out_dir, exist_ok=True)
    stem = Path(video_path).stem

    transcript = transcribe(video_path, language=language, word_timestamps=True)
    words = transcript.get("words") or []
    if not words:
        # Fallback: treat segments as single "words"
        words = [
            {"start": float(s["start"]), "end": float(s["end"]), "word": str(s["text"]).strip()}
            for s in transcript.get("segments", [])
            if str(s.get("text", "")).strip()
        ]
    if not words:
        raise RuntimeError("No words/segments to caption.")

    srt_path = os.path.join(out_dir, f"{stem}.srt")
    ass_path = os.path.join(out_dir, f"{stem}.ass")
    write_srt(words, srt_path)
    write_ass(words, ass_path)
    print(f"[captions] wrote {srt_path}", flush=True)
    print(f"[captions] wrote {ass_path}", flush=True)

    result = {"srt": srt_path, "ass": ass_path}
    if burn:
        burned = os.path.join(out_dir, f"{stem}_captioned.mp4")
        burn_subtitles(video_path, ass_path, burned)
        print(f"[captions] burned → {burned}", flush=True)
        result["burned"] = burned
    return result

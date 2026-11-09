"""Shorts-style captions from a local video file. Independent of the clip pipeline.

The same ASS generator is used by the standalone captions CLI (sentence or
word input) and by the 9:16 renderer, so burned captions always use a
1080×1920 PlayRes canvas and a bottom safe zone instead of libass's default
384×288 script canvas.
"""
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .config import (
    CAPTION_FONT,
    CAPTION_FONT_SIZE,
    CAPTION_HIGHLIGHT_COLOR,
    CAPTION_MARGIN_V,
    CAPTION_MAX_CHARS,
    CAPTION_MAX_WORDS,
    SHORTS_CRF,
    SHORTS_HEIGHT,
    SHORTS_WIDTH,
)

_MIN_FONT_SIZE = 56
_WHITE = "&H00FFFFFF"
_PUNCT_ONLY = {",", ".", "?", "!", ";", ":", "..", "..."}


def _ass_timestamp(seconds: float) -> str:
    """ASS uses H:MM:SS.cc (centiseconds) with carry-safe rounding."""
    total_cs = max(0, int(round(float(seconds) * 100)))
    h, rem = divmod(total_cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_escape(text: str) -> str:
    """Escape text for an ASS Dialogue event (not for override tags)."""
    text = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}")


def _word_text(word: Dict) -> str:
    return str(word.get("word") or word.get("text") or "").strip()


def _clean_words(words: List[Dict]) -> List[Dict]:
    clean: List[Dict] = []
    for w in sorted(words, key=lambda item: float(item.get("start", 0.0))):
        text = _word_text(w)
        if not text:
            continue
        try:
            start = float(w["start"])
            end = float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.05
        if text in _PUNCT_ONLY:
            if clean:
                clean[-1]["text"] += text
            continue
        clean.append({"start": start, "end": end, "text": text})
    return clean


def _chunk_words(
    words: List[Dict],
    max_words: int = CAPTION_MAX_WORDS,
    max_span: float = 2.8,
    max_chars: int = CAPTION_MAX_CHARS,
) -> List[List[Dict]]:
    """Group word timestamps into short, readable caption cues.

    Splits on word count, span, or punctuation. The caller renders one cue at a
    time; this function only groups, it does not set final cue times.
    """
    clean = _clean_words(words)
    if not clean:
        return []

    chunks: List[List[Dict]] = []
    current: List[Dict] = []
    for word in clean:
        if current:
            span = word["end"] - current[0]["start"]
            chars = sum(len(w["text"]) + 1 for w in current) + len(word["text"])
            ends_sentence = current[-1]["text"].endswith((".", "!", "?", ";", ":"))
            if len(current) >= max_words or span > max_span or chars > max_chars or ends_sentence:
                chunks.append(current)
                current = []
        current.append(word)
    if current:
        chunks.append(current)
    return chunks


def _wrap_text(text: str, max_chars: int) -> str:
    """Break a caption into at most two balanced ASS lines with ``\\N``."""
    words = text.split()
    if not words:
        return ""
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    if len(lines) > 2:
        # Keep two lines by re-balancing the whole text instead of truncating.
        half = max(1, len(words) // 2)
        left = " ".join(words[:half])
        right = " ".join(words[half:])
        lines = [left, right]
    return r"\N".join(lines)


def _word_events(
    chunks: List[List[Dict]],
    highlight: str,
    clip_start: float,
    clip_end: Optional[float],
) -> List[str]:
    events: List[str] = []
    prev_end = 0.0
    for chunk in chunks:
        chunk_start = max(prev_end, max(0.0, float(chunk[0]["start"]) - clip_start))
        chunk_end = max(chunk_start, float(chunk[-1]["end"]) - clip_start)
        if clip_end is not None:
            chunk_end = min(chunk_end, clip_end)
        if chunk_end <= chunk_start:
            continue
        prev_end = chunk_end
        display = " ".join(_ass_escape(w["text"]) for w in chunk)
        if not highlight or highlight.lower() == "none":
            events.append(
                f"Dialogue: 0,{_ass_timestamp(chunk_start)},{_ass_timestamp(chunk_end)},"
                f"Default,,0,0,0,,{display}"
            )
            continue
        for i, word in enumerate(chunk):
            w_start = max(chunk_start, float(word["start"]) - clip_start)
            if i < len(chunk) - 1:
                w_end = min(float(chunk[i + 1]["start"]) - clip_start, chunk_end)
            else:
                w_end = chunk_end
            if w_end <= w_start:
                w_end = min(chunk_end, w_start + 0.05)
            if w_end <= w_start:
                continue
            parts = []
            for j, other in enumerate(chunk):
                token = _ass_escape(other["text"])
                if j == i:
                    parts.append(r"{\c" + highlight + "}" + token + r"{\c" + _WHITE + "&}")
                else:
                    parts.append(token)
            events.append(
                f"Dialogue: 0,{_ass_timestamp(w_start)},{_ass_timestamp(w_end)},"
                f"Default,,0,0,0,,{' '.join(parts)}"
            )
    return events


def _segment_events(
    segments: List[Dict],
    clip_start: float,
    clip_end: float,
    max_words: int,
    max_chars: int,
) -> List[str]:
    """Sentence/segment fallback: split long cues and clamp overlaps."""
    cues: List[Dict] = []
    for segment in sorted(segments, key=lambda s: float(s.get("start", 0.0))):
        text = str(segment.get("text", "")).strip()
        if not text:
            continue
        start = max(0.0, float(segment.get("start", 0.0)) - clip_start)
        end = min(float(segment.get("end", start)) - clip_start, clip_end)
        if end <= 0 or start >= clip_end:
            continue
        start = max(0.0, start)
        end = max(start + 0.1, end)

        tokens = text.split()
        if not tokens:
            continue
        groups: List[List[str]] = []
        current: List[str] = []
        for token in tokens:
            if current and (len(current) >= max_words or
                            len(" ".join(current + [token])) > max_chars):
                groups.append(current)
                current = []
            current.append(token)
        if current:
            groups.append(current)

        total_chars = max(1, sum(len(" ".join(g)) for g in groups))
        cursor = start
        for group in groups:
            share = (end - start) * (len(" ".join(group)) / total_chars)
            cue_end = min(end, cursor + max(0.15, share))
            cues.append({
                "start": cursor,
                "end": max(cursor + 0.1, cue_end),
                "text": " ".join(group),
            })
            cursor = cue_end
        if cues:
            cues[-1]["end"] = max(cues[-1]["start"] + 0.1, end)

    events: List[str] = []
    for i, cue in enumerate(cues):
        start = cue["start"]
        end = cue["end"]
        if i + 1 < len(cues):
            end = min(end, max(start + 0.05, cues[i + 1]["start"]))
        if end <= start:
            continue
        text = _ass_escape(_wrap_text(cue["text"], max_chars))
        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},"
            f"Default,,0,0,0,,{text}"
        )
    return events


def build_ass(
    items: List[Dict],
    out_path: str,
    clip_start: float = 0.0,
    clip_end: Optional[float] = None,
    max_words: int = CAPTION_MAX_WORDS,
    max_chars: int = CAPTION_MAX_CHARS,
    font: str = CAPTION_FONT,
    font_size: int = CAPTION_FONT_SIZE,
    highlight: str = CAPTION_HIGHLIGHT_COLOR,
    margin_v: int = CAPTION_MARGIN_V,
) -> str:
    """Write a shorts-ready ASS file from words *or* sentence segments.

    Word input (``{"word", "start", "end"}``) produces karaoke-style
    per-word highlight events. Sentence input (``{"text", "start", "end"}``)
    is split into readable cues and clamped so cues never overlap.
    """
    font_size = max(_MIN_FONT_SIZE, int(font_size))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {SHORTS_WIDTH}
PlayResY: {SHORTS_HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{font_size},{_WHITE},{highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,60,60,{max(40, int(margin_v))},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if items and any("word" in item for item in items):
        words = [
            {**item, "start": float(item.get("start", 0.0)), "end": float(item.get("end", 0.0))}
            for item in items
        ]
        cut_end = clip_end
        events = _word_events(
            _chunk_words(words, max_words=max_words, max_chars=max_chars),
            highlight,
            clip_start,
            cut_end,
        )
    else:
        cut_end = clip_end if clip_end is not None else max(
            (float(s.get("end", 0.0)) for s in items), default=0.0
        )
        events = _segment_events(
            items, clip_start, max(0.1, cut_end), max_words, max_chars
        )

    Path(out_path).write_text(header + "\n".join(events) + "\n", encoding="utf-8")
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
    return build_ass(
        words,
        out_path,
        max_words=max_words,
        font=font,
        font_size=font_size,
        highlight=highlight,
    )


def has_audio(path: str) -> bool:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True
    return proc.returncode == 0 and bool(proc.stdout.strip())


def burn_subtitles(video_path: str, ass_path: str, out_path: str, audio_present: Optional[bool] = None) -> str:
    """Burn an ASS file onto a video at the configured short quality."""
    ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:").replace("'", r"\'")
    if audio_present is None:
        audio_present = has_audio(video_path)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vf", f"ass='{ass_escaped}'",
        "-c:v", "libx264", "-preset", "fast", "-crf", str(SHORTS_CRF),
        "-movflags", "+faststart",
    ]
    if audio_present:
        cmd += [
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
        ]
    else:
        cmd += ["-an"]
    cmd.append(out_path)
    subprocess.run(cmd, check=True)
    return out_path


def write_srt(words: List[Dict], out_path: str, max_words: int = CAPTION_MAX_WORDS) -> str:
    chunks = _chunk_words(words, max_words=max_words)
    lines = []
    for i, chunk in enumerate(chunks, 1):
        start = float(chunk[0]["start"])
        end = float(chunk[-1]["end"])
        text = " ".join(w["text"] for w in chunk)
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    Path(out_path).write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _srt_timestamp(seconds: float) -> str:
    ms = max(0, int(round(float(seconds) * 1000)))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


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

    from .transcriber import transcribe

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

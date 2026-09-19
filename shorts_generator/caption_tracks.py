"""Select and download the *original* YouTube caption track.

YouTube serves one original caption track per video (transcribed in the
detected audio language) plus auto-translated copies of it. Requesting a
translated language code — any track whose format URL carries ``tlang=`` —
returns a translation, not a transcription, which is unusable as ASR ground
truth. This module detects track kinds and fetches the original (or an
uploaded human track) so callers like :mod:`shorts_generator.transcripts`
never cache translations by accident.
"""
from __future__ import annotations

import os
from typing import Dict, List, Optional

KIND_UPLOADED = "uploaded"
KIND_ORIGINAL = "original"
KIND_TRANSLATED = "translated"


def base_language(code: Optional[str]) -> str:
    """``en-US`` / ``ne-orig`` → ``en`` / ``ne``; empty codes → ``""``."""
    return (code or "").split("-", 1)[0].strip().lower()


def _is_translated(formats: List[Dict]) -> bool:
    return any("tlang=" in (fmt.get("url") or "") for fmt in formats)


def collect_tracks(info: Dict) -> Dict[str, Dict[str, List[Dict]]]:
    """Split caption formats from a yt-dlp info dict by track kind.

    Uploaded (human) tracks are taken from ``subtitles``; automatic tracks are
    split into originals (no ``tlang=``) and translations (with ``tlang=``).
    Maps are keyed by the raw language code yt-dlp reports.
    """
    tracks: Dict[str, Dict[str, List[Dict]]] = {
        KIND_UPLOADED: {},
        KIND_ORIGINAL: {},
        KIND_TRANSLATED: {},
    }
    for lang, formats in (info.get("subtitles") or {}).items():
        if formats:
            tracks[KIND_UPLOADED].setdefault(lang, list(formats))
    for lang, formats in (info.get("automatic_captions") or {}).items():
        if not formats:
            continue
        kind = KIND_TRANSLATED if _is_translated(formats) else KIND_ORIGINAL
        tracks[kind].setdefault(lang, list(formats))
    return tracks


def _find_lang(mapping: Dict, base: str) -> Optional[str]:
    for code in sorted(mapping):
        if base_language(code) == base:
            return code
    return None


def choose_track(
    info: Dict,
    langs: Optional[List[str]] = None,
    allow_translated: bool = False,
) -> Optional[Dict]:
    """Pick the best literal caption track from a yt-dlp info dict.

    Priority: uploaded subs for a requested language, then the original
    auto-caption for a requested language, then the same two for the video's
    detected language, then any original auto-caption at all. Translated
    tracks are only returned when ``allow_translated=True``.
    """
    tracks = collect_tracks(info)
    wanted = [base_language(lang) for lang in (langs or []) if base_language(lang)]
    video_lang = base_language(info.get("language"))

    order: List[tuple[str, str, str]] = []
    for lang in wanted:
        order.append((KIND_UPLOADED, lang, f"uploaded track for requested language {lang}"))
        order.append((KIND_ORIGINAL, lang, f"original auto-caption for requested language {lang}"))
    if allow_translated:
        for lang in wanted:
            order.append(
                (KIND_TRANSLATED, lang, f"translated track for {lang} (allow_translated=True)")
            )
    if video_lang:
        order.append((KIND_UPLOADED, video_lang, f"uploaded track for video language {video_lang}"))
        order.append((KIND_ORIGINAL, video_lang, f"original auto-caption for video language {video_lang}"))
    for code in sorted(tracks[KIND_ORIGINAL]):
        order.append((KIND_ORIGINAL, base_language(code), f"original auto-caption ({code})"))

    for kind, lang, reason in order:
        code = _find_lang(tracks[kind], lang)
        if code and tracks[kind][code]:
            return {
                "kind": kind,
                "lang": code,
                "base_lang": base_language(code),
                "reason": reason,
                "formats": tracks[kind][code],
            }

    if allow_translated:
        for code in sorted(tracks[KIND_TRANSLATED]):
            if tracks[KIND_TRANSLATED][code]:
                return {
                    "kind": KIND_TRANSLATED,
                    "lang": code,
                    "base_lang": base_language(code),
                    "reason": f"translated track ({code}, allow_translated=True)",
                    "formats": tracks[KIND_TRANSLATED][code],
                }
    return None


def fetch_source_subs(
    video_url: str,
    out_dir: str,
    video_id: str,
    language: Optional[str] = None,
    langs: Optional[List[str]] = None,
    allow_translated: bool = False,
    cookies_from_browser: Optional[str] = None,
) -> Optional[str]:
    """Download the video's original (or uploaded) caption track as SRT.

    Keeps the legacy ``source_<id>_auto.<lang>.srt`` filename so
    :func:`shorts_generator.transcripts._promote_fetched` keeps working.
    Returns the caption path, or ``None`` when no literal track exists.
    """
    import yt_dlp  # lazy: keeps the module import-safe without the dependency

    prefix = f"source_{video_id}_auto"
    os.makedirs(out_dir, exist_ok=True)
    for name in sorted(os.listdir(out_dir)):
        if name.startswith(prefix) and name.endswith((".srt", ".vtt")):
            return os.path.join(out_dir, name)

    requested = langs or ([language] if language else None)
    try:
        with yt_dlp.YoutubeDL({"skip_download": True, "quiet": True, "no_warnings": True}) as probe:
            info = probe.extract_info(video_url, download=False)
        track = choose_track(info, langs=requested, allow_translated=allow_translated)
        if not track:
            return None

        opts: Dict = {
            "skip_download": True,
            "writesubtitles": track["kind"] == KIND_UPLOADED,
            "writeautomaticsub": track["kind"] != KIND_UPLOADED,
            "subtitleslangs": [track["lang"]],
            "subtitlesformat": "srt",
            "convert_subs": ["srt"],
            "outtmpl": os.path.join(out_dir, prefix + ".%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
        }
        if cookies_from_browser:
            opts["cookiesfrombrowser"] = (cookies_from_browser,)
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(video_url, download=True)
    except Exception:
        return None

    for name in sorted(os.listdir(out_dir)):
        if name.startswith(prefix) and name.endswith((".srt", ".vtt")):
            return os.path.join(out_dir, name)
    return None

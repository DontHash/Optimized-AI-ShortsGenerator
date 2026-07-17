import os

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()

LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto")  # auto / cpu / cuda
OUTPUT_DIR = os.getenv("LOCAL_OUTPUT_DIR", os.getenv("OUTPUT_DIR", "output"))
# max / highest = uncapped (YoutubeDownloader Highest); or 360/480/720/1080
DOWNLOAD_FORMAT = os.getenv("DOWNLOAD_FORMAT", "max")

# VAD for faster-whisper — off by default (too aggressive on mixed speech/music)
LOCAL_WHISPER_VAD_FILTER = os.getenv("LOCAL_WHISPER_VAD_FILTER", "false").strip().lower() == "true"
_vad_params_env = os.getenv("LOCAL_WHISPER_VAD_PARAMETERS", "")
if _vad_params_env:
    import json
    LOCAL_WHISPER_VAD_PARAMETERS = json.loads(_vad_params_env)
else:
    LOCAL_WHISPER_VAD_PARAMETERS = {
        "threshold": 0.5,
        "min_speech_duration_ms": 250,
        "max_speech_duration_s": float("inf"),
        "min_silence_duration_ms": 2000,
        "speech_pad_ms": 400,
    }

# Captions style
CAPTION_FONT = os.getenv("CAPTION_FONT", "Arial")
CAPTION_FONT_SIZE = int(os.getenv("CAPTION_FONT_SIZE", "48"))
CAPTION_HIGHLIGHT_COLOR = os.getenv("CAPTION_HIGHLIGHT_COLOR", "&H0000FFFF")  # ASS BGR yellow
CAPTION_MAX_WORDS = int(os.getenv("CAPTION_MAX_WORDS", "3"))

BOUNDARY_PAD_SECONDS = float(os.getenv("BOUNDARY_PAD_SECONDS", "0.3"))

# --- Signal-fusion reranker (see UPLIFT_PLAN.md) ---
# Weights per signal; missing signals drop out and remaining weights renormalize.
_DEFAULT_WEIGHTS = {"llm": 0.45, "replay": 0.25, "audio": 0.20, "chapter": 0.10}


def _parse_weights(raw: str) -> dict:
    if not raw.strip():
        return dict(_DEFAULT_WEIGHTS)
    weights = dict(_DEFAULT_WEIGHTS)
    for part in raw.split(","):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().lower()
        try:
            weights[k] = float(v)
        except ValueError:
            continue
    return weights


RERANK_WEIGHTS = _parse_weights(os.getenv("RERANK_WEIGHTS", ""))

# Audio-energy scoring toggle (needs ffmpeg + numpy; both already required)
AUDIO_ENERGY_ENABLED = os.getenv("AUDIO_ENERGY", "true").strip().lower() != "false"

# Context-aware peak expansion (3.7): capture the setup that leads into a peak
PEAK_LEAD_SECONDS = float(os.getenv("PEAK_LEAD_SECONDS", "5"))
PEAK_LEAD_MAX_SECONDS = float(os.getenv("PEAK_LEAD_MAX_SECONDS", "20"))
PEAK_TAIL_SECONDS = float(os.getenv("PEAK_TAIL_SECONDS", "5"))
MAX_CLIP_SECONDS = float(os.getenv("MAX_CLIP_SECONDS", "180"))

# Transcript-similarity dedupe: drop the lower-scoring of two near-identical clips
DEDUPE_SIMILARITY = float(os.getenv("DEDUPE_SIMILARITY", "0.6"))


def require_openai_key() -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to your .env or export it, "
            "or set LLM_PROVIDER=gemini."
        )
    return OPENAI_API_KEY


def require_gemini_key() -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env or export it, "
            "or set LLM_PROVIDER=openai."
        )
    return GEMINI_API_KEY

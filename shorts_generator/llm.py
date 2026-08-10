"""LLM backend — OpenAI or Gemini, selected by LLM_PROVIDER.

Resilience: transient errors (rate limits, timeouts, 5xx) are retried with
exponential backoff; if the primary provider stays down and the other provider
has a key configured, we fall back to it (opt out with LLM_FALLBACK=false).
"""
import time

from .config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    LLM_FALLBACK_ENABLED,
    LLM_MAX_RETRIES,
    LLM_PROVIDER,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    require_gemini_key,
    require_openai_key,
)


def call_openai_llm(prompt: str) -> str:
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required. Install it with:\n    pip install -r requirements.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_gemini_llm(prompt: str) -> str:
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from e

    client = genai.Client(api_key=require_gemini_key())
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
    )
    return response.text or ""


_TRANSIENT_MARKERS = (
    "rate_limit",
    "rate limit",
    "ratelimit",
    "429",
    "timeout",
    "timed out",
    "deadline",
    "503",
    "502",
    "500",
    "overloaded",
    "resource_exhausted",
    "temporarily",
    "retry",
)


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _TRANSIENT_MARKERS)


def _provider_chain() -> list:
    """Ordered list of providers to try: primary first, then the other if configured."""
    primary = (LLM_PROVIDER or "gemini").strip().lower()
    chain = [primary]
    if LLM_FALLBACK_ENABLED:
        other = "openai" if primary == "gemini" else "gemini"
        if other == "openai" and OPENAI_API_KEY:
            chain.append("openai")
        elif other == "gemini" and GEMINI_API_KEY:
            chain.append("gemini")
    return chain


def call_llm(prompt: str) -> str:
    """Call the configured LLM with retry + cross-provider fallback."""
    chain = _provider_chain()
    last_err: Exception = RuntimeError("no LLM provider available")

    for idx, provider in enumerate(chain):
        fn = call_openai_llm if provider == "openai" else call_gemini_llm
        for attempt in range(1, LLM_MAX_RETRIES + 1):
            try:
                return fn(prompt)
            except Exception as e:  # noqa: BLE001
                last_err = e
                if not _is_transient(e) or attempt == LLM_MAX_RETRIES:
                    break
                backoff = 2 ** (attempt - 1)
                print(
                    f"[llm] {provider} transient error (attempt {attempt}/{LLM_MAX_RETRIES}); "
                    f"retry in {backoff}s: {e}",
                    flush=True,
                )
                time.sleep(backoff)
        if idx < len(chain) - 1:
            print(f"[llm] {provider} exhausted; falling back to {chain[idx + 1]}", flush=True)

    raise RuntimeError(f"LLM call failed after {LLM_MAX_RETRIES} retries across {chain}: {last_err}")

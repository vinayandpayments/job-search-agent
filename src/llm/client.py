"""The single entry point for all LLM (Gemini) calls.

Per CLAUDE.md, model names, API keys, rate limiting, and (later) caching config
are referenced only here. Business logic must not call the ``google-genai`` SDK
directly.

Two generation helpers are exposed:
  - ``generate_text``       : plain text out
  - ``generate_structured`` : schema-validated pydantic object out (used by the
                              ingestion extractor and, later, the agent tools)

Every call passes through a process-wide rate limiter, because the free-tier
Gemini key has tight per-minute limits (see ``config.GEMINI_RPM``).
"""

from __future__ import annotations

import threading
import time
from functools import lru_cache

from google import genai
from google.genai import types
from pydantic import BaseModel

from src.config import GEMINI_RPM, get_settings


class _RateLimiter:
    """Process-wide minimum-interval limiter, shared by all LLM calls.

    Not a token bucket — just enforces a minimum gap between consecutive
    requests, which is enough to stay under a requests-per-minute ceiling on
    the free tier. Thread-safe so concurrent callers serialize cleanly.
    """

    def __init__(self, rpm: int) -> None:
        self._min_interval = 60.0 / rpm if rpm > 0 else 0.0
        self._lock = threading.Lock()
        self._last_call = 0.0

    def wait(self) -> None:
        """Block until enough time has elapsed since the previous call."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_call = time.monotonic()


_rate_limiter = _RateLimiter(GEMINI_RPM)


@lru_cache(maxsize=1)
def get_client() -> genai.Client:
    """Return a cached Gemini client authenticated from the environment.

    Raises:
        RuntimeError: If ``GEMINI_API_KEY`` is not set. Failing here with a
            clear message beats an opaque 401 from the API later.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return genai.Client(api_key=settings.gemini_api_key)


def generate_text(prompt: str, model: str) -> str:
    """Generate plain text from a single prompt.

    Args:
        prompt: The user prompt to send.
        model: The Gemini model id (see model constants in ``src.config``).

    Returns:
        The model's text response, stripped of surrounding whitespace.
    """
    client = get_client()
    _rate_limiter.wait()
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()


def generate_structured[T: BaseModel](prompt: str, model: str, schema: type[T]) -> T:
    """Generate a schema-validated object from a single prompt.

    Uses Gemini's JSON mode with a pydantic ``response_schema``; the SDK parses
    and validates the response into an instance of ``schema``.

    Args:
        prompt: The user prompt to send.
        model: The Gemini model id (see model constants in ``src.config``).
        schema: A pydantic model class describing the expected output.

    Returns:
        A validated instance of ``schema``.

    Raises:
        ValueError: If the response could not be parsed into ``schema``.
    """
    client = get_client()
    _rate_limiter.wait()
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
        ),
    )
    parsed = response.parsed
    if not isinstance(parsed, schema):
        raise ValueError(f"Gemini did not return a valid {schema.__name__}: {response.text!r}")
    return parsed

"""The single entry point for all LLM (Gemini) calls.

Per CLAUDE.md, model names, API keys, and (later) caching config are referenced
only here. Business logic must not call the ``google-genai`` SDK directly.

Phase 0 exposes just a client factory and a plain text-generation helper. The
schema-constrained extraction helper lives in ``extraction.py`` (Phase 1), and
caching config lands in Phase 3 once the agent's stable prefix exists.
"""

from __future__ import annotations

from functools import lru_cache

from google import genai

from src.config import get_settings


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
    response = client.models.generate_content(model=model, contents=prompt)
    return (response.text or "").strip()

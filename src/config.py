"""Central configuration: paths, model names, and API keys.

This is the single source of truth for filesystem paths and model choices.
Nothing else in the codebase should hard-code a model name or a data path.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Paths -------------------------------------------------------------------
# PROJECT_ROOT is the repo root: this file is at <root>/src/config.py.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = PROJECT_ROOT / "data"
SQLITE_PATH: Path = DATA_DIR / "jobs.db"
CHROMA_DIR: Path = DATA_DIR / "chroma"

# --- Model choices (see PLAN.md §4.3) ----------------------------------------
# Primary provider is Google Gemini. Flash = cheap high-volume tasks,
# Pro = reasoning-heavy / user-facing tasks.
#
# NOTE (Day 0): the API key is FREE-TIER and billing is intentionally OFF. Free
# tier has no usable Pro quota (Gemini Pro returns 429 free_tier_input_tokens
# exhausted) and can no longer call gemini-2.5-* ("no longer available to new
# users"). Decision: run Flash across the board and NOT enable billing. If Flash
# quality proves insufficient for the agent tier, fall back to a free/open-source
# model (e.g. a local model via Ollama) rather than paying for Pro.
EXTRACTION_MODEL: str = "gemini-3.5-flash-lite"  # cheap, high-volume (extraction, summaries)
AGENT_MODEL: str = "gemini-3.6-flash"  # best free-tier Flash; agent/user-facing tasks
SUMMARY_MODEL: str = "gemini-3.5-flash-lite"

# Local embedding model — no API calls, zero marginal cost.
EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"


class Settings(BaseSettings):
    """Runtime settings loaded from the environment / `.env`.

    Only secrets and per-environment values live here. Static choices
    (paths, model names) are module-level constants above.
    """

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""


def get_settings() -> Settings:
    """Return the loaded settings.

    Kept as a function (rather than a module-level singleton) so tests can
    construct settings with a patched environment without import-time side
    effects.
    """
    return Settings()

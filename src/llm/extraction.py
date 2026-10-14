"""LLM-based structured extraction for ingestion (Gemini Flash).

This is the "fill the gaps" half of the map-first strategy (PLAN.md §4.3 note):
clean sources like RemoteOK already give us most structured fields directly, so
the LLM is only asked to infer what the raw data *doesn't* carry — chiefly the
required years of experience and a seniority label, which we read out of the
free-text description.

Per CLAUDE.md, the prompt text and its output schema live here (not inline in
ingestion code), and the actual API call goes through ``src.llm.client``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.config import EXTRACTION_MODEL
from src.llm.client import generate_structured

# Cap the description we send — the seniority signal is almost always near the
# top, and this keeps input tokens (and free-tier quota) small.
_MAX_DESCRIPTION_CHARS = 4000


class JobGaps(BaseModel):
    """Fields inferred from a job description that the source doesn't provide."""

    experience_years: int | None = Field(
        default=None,
        description="Minimum years of professional experience required, if stated or "
        "clearly implied. Null if not determinable.",
    )
    seniority_level: str | None = Field(
        default=None,
        description="One of: intern, junior, mid, senior, staff, lead, principal. "
        "Null if not determinable.",
    )


_PROMPT_TEMPLATE = """\
You are a precise information-extraction tool for a job-search system.

From the job posting below, extract ONLY what is explicitly stated or clearly \
implied. Do NOT guess or invent. If a field is not determinable from the text, \
return null for it.

Return:
- experience_years: the minimum years of professional experience required \
(integer), or null.
- seniority_level: one of intern, junior, mid, senior, staff, lead, principal, \
or null.

Role: {role}
Company: {company}

Description:
{description}
"""


def extract_job_gaps(role: str, company: str, description: str) -> JobGaps:
    """Infer the fields a structured source doesn't provide.

    Args:
        role: The job title.
        company: The hiring company.
        description: The (plain-text) job description.

    Returns:
        A ``JobGaps`` with best-effort inferred fields; any field the model
        can't determine comes back as ``None`` (no fabrication).
    """
    prompt = _PROMPT_TEMPLATE.format(
        role=role,
        company=company,
        description=description[:_MAX_DESCRIPTION_CHARS],
    )
    return generate_structured(prompt, model=EXTRACTION_MODEL, schema=JobGaps)

"""Chunking for the embedding path.

Splits a job's text into overlapping chunks for embedding into ChromaDB. Uses
LangChain's ``RecursiveCharacterTextSplitter`` (pre-approved in PLAN.md §4.6 for
its well-tuned separator defaults).

Only the semantic/embedding path is chunked — structured facts go to SQLite
whole (see ``pipeline.py``). Each chunk is prefixed with a compact header
(role @ company) so a retrieved fragment still carries identifying context.
"""

from __future__ import annotations

from langchain_text_splitters import RecursiveCharacterTextSplitter

from src.config import CHUNK_OVERLAP, CHUNK_SIZE
from src.ingestion.normalizer import NormalizedJob

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    length_function=len,
)


def chunk_job(job: NormalizedJob) -> list[str]:
    """Split a job into embeddable text chunks.

    Args:
        job: The normalized job to chunk.

    Returns:
        A list of text chunks. Always at least one chunk (the header) even if
        the description is empty, so every job is represented in the vector
        store.
    """
    header = f"{job.role} @ {job.company}"
    body = f"{header}\n\n{job.description}".strip()
    chunks = _splitter.split_text(body)
    return chunks or [header]

"""ChromaDB storage: persistent client and the jobs collection.

Vectors live here and only here; structured facts live in SQLite (see
``db.py``). Embeddings are computed locally with
``sentence-transformers/all-MiniLM-L6-v2`` — no API calls, zero marginal cost
(PLAN.md §4.3).

This is intentionally thin for Phase 0. Full ingestion wiring (chunk → embed →
upsert with metadata) arrives in Phase 1.
"""

from __future__ import annotations

from pathlib import Path

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from chromadb.utils import embedding_functions

from src.config import CHROMA_DIR, EMBEDDING_MODEL

JOBS_COLLECTION = "jobs"


def get_embedding_function() -> embedding_functions.EmbeddingFunction:
    """Return the local sentence-transformers embedding function.

    Downloads the model weights on first use, then runs fully offline. Using
    ChromaDB's built-in wrapper means the collection embeds queries and
    documents with the same model automatically.
    """
    return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)


def get_client(persist_dir: Path = CHROMA_DIR) -> ClientAPI:
    """Return a persistent ChromaDB client rooted at ``persist_dir``.

    Args:
        persist_dir: Directory for ChromaDB's on-disk files. Created if missing.

    Returns:
        A ``PersistentClient`` instance.
    """
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def get_jobs_collection(persist_dir: Path = CHROMA_DIR) -> Collection:
    """Get or create the ``jobs`` collection with the local embedder attached.

    Args:
        persist_dir: Directory for ChromaDB's on-disk files.

    Returns:
        The ``jobs`` ``Collection``, ready for add/query calls.
    """
    client = get_client(persist_dir)
    return client.get_or_create_collection(
        name=JOBS_COLLECTION,
        embedding_function=get_embedding_function(),
        metadata={"hnsw:space": "cosine"},
    )

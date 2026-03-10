"""
EmbeddingService — wraps sentence-transformers for incident vector generation.

Design rationale:
- Singleton model: loading all-MiniLM-L6-v2 takes ~2s and 80MB RAM. We load once
  per Celery worker process (via lazy init) and reuse across tasks.
- Thread-safe: SentenceTransformer.encode() releases the GIL during inference,
  so multiple Celery threads can call embed_text() concurrently without contention.
- CPU-only: No GPU required. Inference takes ~10-50ms per text on modern CPU.
  For AIRRA's throughput (1-5 incidents/minute) this is negligible.

Model choice — all-MiniLM-L6-v2:
- 384 dimensions (compact for storage + cosine search)
- Trained on 1B+ sentence pairs (good generalisation over technical text)
- 80MB model size (fits in container RAM without issue)
- MIT license
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.models.incident import Incident

_MODEL_LOCK = threading.Lock()


class EmbeddingService:
    MODEL_NAME = "all-MiniLM-L6-v2"
    DIMS = 384

    def __init__(self) -> None:
        self._model = None  # lazy-loaded on first call

    def _get_model(self):
        """Lazy-load the sentence-transformers model (thread-safe singleton)."""
        if self._model is None:
            with _MODEL_LOCK:
                if self._model is None:
                    try:
                        from sentence_transformers import SentenceTransformer  # type: ignore
                        logger.info(f"Loading embedding model {self.MODEL_NAME} ...")
                        self._model = SentenceTransformer(self.MODEL_NAME)
                        logger.info(f"Embedding model loaded ({self.DIMS} dims)")
                    except ImportError as e:
                        raise RuntimeError(
                            "sentence-transformers not installed. "
                            "Add sentence-transformers>=2.7.0 to requirements.txt"
                        ) from e
        return self._model

    def embed_text(self, text: str) -> list[float]:
        """
        Embed a single text string.

        Returns:
            384-dimensional float list suitable for pgvector storage.
        """
        model = self._get_model()
        # normalize_embeddings=True ensures cosine similarity == dot product,
        # which aligns with pgvector's vector_cosine_ops index.
        vector = model.encode(text, normalize_embeddings=True)
        return vector.tolist()

    def embed_incident(self, incident: "Incident", extra_context: dict | None = None) -> list[float]:
        """
        Embed an incident using IncidentSummarizer's structured text.

        Secret redaction is applied between summarize() and encode() so that
        credentials that appear in logs / metrics snapshots are never stored
        permanently in the vector DB (OWASP LLM06: Sensitive Information Disclosure).

        Args:
            incident: The Incident ORM object.
            extra_context: Optional enrichment (root_cause, resolution) for resolved incidents.

        Returns:
            384-dimensional float list.
        """
        from app.services.incident_summarizer import get_summarizer
        from app.services.secret_redactor import redact_secrets

        summarizer = get_summarizer()
        text = summarizer.summarize(incident, extra_context=extra_context)

        # Redact secrets before encoding — embeddings are permanent and cannot
        # be selectively purged from pgvector without full re-indexing.
        text, secret_count = redact_secrets(text)
        if secret_count:
            logger.warning(
                "embed_incident redacted %d secret(s) from incident %s before encoding",
                secret_count,
                incident.id,
            )

        logger.debug(f"Embedding incident {incident.id} — text length: {len(text)} chars")
        return self.embed_text(text)


# Process-level singleton — one model per Celery worker process
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service

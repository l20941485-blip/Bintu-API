"""Privacy-preserving observability for RAG answer generation."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RagAnswerObservability:
    """Metrics for one RAG answer request.

    This event intentionally contains identifiers and counts only. It must
    never contain query text, chunk text, document titles, or URLs.
    """

    query_length: int
    retrieved_chunk_count: int
    selected_evidence_count: int
    citation_count: int
    insufficient_evidence: bool
    latency_ms: float
    retrieved_chunk_ids: tuple[str, ...]
    citation_chunk_ids: tuple[str, ...]
    access_label_count: int
    has_owner_identity: bool


class RagAnswerObserver(Protocol):
    """Receives privacy-preserving RAG answer metrics."""

    def record_answer(
        self,
        event: RagAnswerObservability,
    ) -> None:
        ...


class LoggingRagAnswerObserver:
    """Emits structured RAG answer metrics through standard logging."""

    def record_answer(
        self,
        event: RagAnswerObservability,
    ) -> None:
        logger.info(
            "rag.answer.completed",
            extra={"rag_answer": asdict(event)},
        )

"""Grounded, extractive answer generation for the RAG knowledge core."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from bintu_api.rag.observability import (
    RagAnswerObservability,
    RagAnswerObserver,
)
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "do",
        "for",
        "how",
        "i",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "what",
        "with",
    }
)


@dataclass(frozen=True)
class RagCitation:
    """A chunk-level citation attached to a grounded answer."""

    chunk_id: str
    revision_id: str
    document_id: str
    source_url: str
    final_url: str | None
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class RagAnswer:
    """A grounded answer and the evidence used to produce it."""

    answer: str
    citations: tuple[RagCitation, ...]
    retrieved_chunks: tuple[RetrievedChunk, ...]
    insufficient_evidence: bool


class RagAnswerService:
    """Produces extractive answers strictly from retrieved evidence."""

    def __init__(
        self,
        retrieval_service: RagRetrievalService,
        *,
        observer: RagAnswerObserver | None = None,
    ) -> None:
        self._retrieval_service = retrieval_service
        self._observer = observer

    async def answer(
        self,
        *,
        query: str,
        limit: int = 5,
        access_labels: tuple[str, ...] = (),
        owner_identity: str | None = None,
        document_id: str | None = None,
    ) -> RagAnswer:
        started_at = time.perf_counter()
        query_terms = self._query_terms(query)

        chunks = await self._retrieval_service.search(
            query=query,
            limit=limit,
            access_labels=access_labels,
            owner_identity=owner_identity,
            document_id=document_id,
        )

        if not chunks:
            answer = RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=(),
                insufficient_evidence=True,
            )
            self._record(
                query=query,
                answer=answer,
                access_labels=access_labels,
                owner_identity=owner_identity,
                started_at=started_at,
            )
            return answer

        evidence = self._select_evidence(chunks, query_terms)

        if not evidence:
            answer = RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=tuple(chunks),
                insufficient_evidence=True,
            )
            self._record(
                query=query,
                answer=answer,
                access_labels=access_labels,
                owner_identity=owner_identity,
                started_at=started_at,
            )
            return answer

        citations: list[RagCitation] = []
        seen_citation_chunks: set[str] = set()
        for chunk, _, _ in evidence:
            if chunk.chunk_id in seen_citation_chunks:
                continue
            seen_citation_chunks.add(chunk.chunk_id)
            citations.append(self._to_citation(chunk))

        answer = RagAnswer(
            answer=" ".join(statement for _, statement, _ in evidence),
            citations=tuple(citations),
            retrieved_chunks=tuple(chunks),
            insufficient_evidence=False,
        )
        self._record(
            query=query,
            answer=answer,
            access_labels=access_labels,
            owner_identity=owner_identity,
            started_at=started_at,
        )
        return answer

    def _score_candidates(
        self,
        chunks: tuple[RetrievedChunk, ...],
        query_terms: frozenset[str],
    ) -> list[tuple[int, int, int, RetrievedChunk, str]]:
        candidates: list[tuple[int, int, int, RetrievedChunk, str]] = []
        seen_statements: set[str] = set()

        for chunk_index, chunk in enumerate(chunks):
            heading_terms = self._terms(
                " ".join(chunk.heading_path)
            )

            for statement_index, statement in enumerate(
                self._candidate_statements(chunk.text)
            ):
                normalized = statement.casefold()
                if normalized in seen_statements:
                    continue

                statement_terms = self._terms(statement)
                matched_terms = query_terms & (
                    statement_terms | heading_terms
                )
                score = len(matched_terms)

                seen_statements.add(normalized)
                candidates.append(
                    (
                        -score,
                        chunk_index,
                        statement_index,
                        chunk,
                        statement,
                    )
                )

        return candidates

    def _select_evidence(
        self,
        chunks: tuple[RetrievedChunk, ...],
        query_terms: frozenset[str],
    ) -> list[tuple[RetrievedChunk, str, int]]:
        candidates = self._score_candidates(chunks, query_terms)
        min_matches = self._min_matches_required(query_terms)
        matching = [
            candidate
            for candidate in candidates
            if -candidate[0] >= min_matches
        ]

        if not matching:
            return []

        matching.sort()

        selected: list[tuple[RetrievedChunk, str, int]] = []
        selected_statements: set[str] = set()

        for _, _, _, chunk, statement in matching:
            normalized = statement.casefold()
            if normalized in selected_statements:
                continue

            selected_statements.add(normalized)
            selected.append((chunk, statement, len(selected)))

            if len(selected) == 3:
                break

        return selected

    @staticmethod
    def _min_matches_required(query_terms: frozenset[str]) -> int:
        return 2 if len(query_terms) >= 3 else 1

    def _candidate_statements(self, text: str) -> list[str]:
        statements: list[str] = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            statements.append(stripped)

        return statements

    def _query_terms(self, query: str) -> frozenset[str]:
        return frozenset(
            term
            for term in self._terms(query)
            if term not in _STOPWORDS
        )

    def _terms(self, text: str) -> frozenset[str]:
        return frozenset(
            self._normalize_term(term)
            for term in re.findall(r"\w+", text)
            if term
        )

    def _normalize_term(self, term: str) -> str:
        normalized = term.casefold()

        if normalized.endswith("ies") and len(normalized) > 4:
            normalized = normalized[:-3] + "y"
        elif normalized.endswith("es") and len(normalized) > 4:
            normalized = normalized[:-2]
        elif normalized.endswith("s") and not normalized.endswith("ss"):
            normalized = normalized[:-1]

        for suffix in ("ation", "tion", "ing", "ed", "ate"):
            if normalized.endswith(suffix) and len(normalized) > len(
                suffix
            ) + 2:
                normalized = normalized[: -len(suffix)]
                break

        return normalized

    def _to_citation(self, chunk: RetrievedChunk) -> RagCitation:
        return RagCitation(
            chunk_id=chunk.chunk_id,
            revision_id=chunk.revision_id,
            document_id=chunk.document_id,
            source_url=chunk.source_url,
            final_url=chunk.final_url,
            heading_path=chunk.heading_path,
        )

    def _record(
        self,
        *,
        query: str,
        answer: RagAnswer,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        started_at: float,
    ) -> None:
        if self._observer is None:
            return

        latency_ms = (time.perf_counter() - started_at) * 1000
        query_terms = self._query_terms(query)
        candidates = self._score_candidates(
            answer.retrieved_chunks,
            query_terms,
        )
        max_statement_matches = max(
            (-candidate[0] for candidate in candidates),
            default=0,
        )

        if not answer.insufficient_evidence:
            abstention_reason: str | None = None
        elif not answer.retrieved_chunks:
            abstention_reason = "no_chunks"
        else:
            abstention_reason = "below_term_threshold"

        self._observer.record_answer(
            RagAnswerObservability(
                query_length=len(query.strip()),
                retrieved_chunk_count=len(answer.retrieved_chunks),
                selected_evidence_count=len(answer.citations),
                citation_count=len(answer.citations),
                insufficient_evidence=answer.insufficient_evidence,
                latency_ms=latency_ms,
                retrieved_chunk_ids=tuple(
                    chunk.chunk_id
                    for chunk in answer.retrieved_chunks
                ),
                citation_chunk_ids=tuple(
                    citation.chunk_id
                    for citation in answer.citations
                ),
                access_label_count=len(access_labels),
                has_owner_identity=owner_identity is not None,
                query_term_count=len(query_terms),
                min_matches_required=self._min_matches_required(query_terms),
                max_statement_matches=max_statement_matches,
                abstention_reason=abstention_reason,
            )
        )

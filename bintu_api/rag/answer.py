"""Grounded, extractive answer generation for the RAG knowledge core."""

from __future__ import annotations

import re
from dataclasses import dataclass

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

    def __init__(self, retrieval_service: RagRetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def answer(
        self,
        *,
        query: str,
        limit: int = 5,
        access_labels: tuple[str, ...] = (),
        owner_identity: str | None = None,
    ) -> RagAnswer:
        query_terms = self._query_terms(query)

        chunks = await self._retrieval_service.search(
            query=query,
            limit=limit,
            access_labels=access_labels,
            owner_identity=owner_identity,
        )

        if not chunks:
            return RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=(),
                insufficient_evidence=True,
            )

        evidence = self._select_evidence(chunks, query_terms)

        if not evidence:
            return RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=tuple(chunks),
                insufficient_evidence=True,
            )

        return RagAnswer(
            answer=" ".join(statement for _, statement, _ in evidence),
            citations=tuple(
                self._to_citation(chunk)
                for chunk, _, _ in evidence
            ),
            retrieved_chunks=tuple(chunks),
            insufficient_evidence=False,
        )

    def _select_evidence(
        self,
        chunks: tuple[RetrievedChunk, ...],
        query_terms: frozenset[str],
    ) -> list[tuple[RetrievedChunk, str, int]]:
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

        matching = [
            candidate
            for candidate in candidates
            if candidate[0] < 0
        ]

        if not matching:
            matching = candidates

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

"""Golden-set evaluation for RAG retrieval quality and answer grounding."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.observability import RagAnswerObservability
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk

GOLDEN_PATH = Path(__file__).with_name("golden_questions.json")
LIMIT = 5


class EvaluationRepository:
    """Deterministic keyword repository used to evaluate retrieval quality."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        stopwords = {
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
        terms = {
            term
            for term in re.findall(r"\w+", query.lower())
            if term and term not in stopwords
        }

        owners = {
            "chunk-private-onboarding": "user-1",
        }

        matches = []
        for chunk in self._chunks:
            words = set(re.findall(r"\w+", chunk.text.lower()))
            heading_words = {
                word
                for heading in chunk.heading_path
                for word in re.findall(r"\w+", heading.lower())
            }

            if not (terms & (words | heading_words)):
                continue

            if access_labels and not any(
                label in chunk.access_labels for label in access_labels
            ):
                continue

            chunk_owner = owners.get(chunk.chunk_id)
            if chunk_owner and chunk_owner != owner_identity:
                continue

            score = len(terms & (words | heading_words)) / len(terms)
            matches.append((score, chunk))

        matches.sort(
            key=lambda item: (-item[0], item[1].chunk_id),
        )
        return [chunk for _, chunk in matches[:limit]]


def make_chunk(
    chunk_id: str,
    text: str,
    score: float,
    *,
    heading_path: tuple[str, ...] = ("Guide",),
    access_labels: tuple[str, ...] = ("public",),
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        revision_id="revision-1",
        document_id="document-1",
        text=text,
        score=score,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        heading_path=heading_path,
        access_labels=access_labels,
    )


def recall_at_k(
    expected: set[str],
    retrieved: list[str],
    k: int = LIMIT,
) -> float:
    if not expected:
        return 1.0

    return len(expected & set(retrieved[:k])) / len(expected)


def precision_at_k(
    expected: set[str],
    retrieved: list[str],
    k: int = LIMIT,
) -> float:
    if not retrieved[:k]:
        return 1.0 if not expected else 0.0

    return len(expected & set(retrieved[:k])) / len(retrieved[:k])


def reciprocal_rank(
    expected: set[str],
    retrieved: list[str],
    k: int = LIMIT,
) -> float:
    for index, chunk_id in enumerate(retrieved[:k], start=1):
        if chunk_id in expected:
            return 1.0 / index

    return 0.0




class _RecordingObserver:
    def __init__(self) -> None:
        self.events: list[RagAnswerObservability] = []

    def record_answer(self, event: RagAnswerObservability) -> None:
        self.events.append(event)


class RagEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.chunks = [
            make_chunk(
                "chunk-guide",
                "# Guide\n\nIntroduction.",
                0.5,
                heading_path=("Guide",),
            ),
            make_chunk(
                "chunk-auth",
                "## Authentication\n\nUse an API key.",
                1.0,
                heading_path=("Guide", "Authentication"),
            ),
            make_chunk(
                "chunk-rate-limits",
                "## Rate limits\n\nRequests are limited to 100 per minute.",
                0.8,
                heading_path=("Guide", "Rate limits"),
            ),
            make_chunk(
                "chunk-private-onboarding",
                "## Onboarding\n\nComplete the private onboarding steps.",
                1.5,
                heading_path=("Onboarding",),
                access_labels=(),
            ),
            make_chunk(
                "chunk-docs-auth",
                "## Authentication\n\nUse an API key.",
                1.0,
                heading_path=("Documentation", "Authentication"),
                access_labels=("docs",),
            ),
            make_chunk(
                "chunk-docs-rate-limits",
                "## Rate limits\n\nRequests are limited to 100 per minute.",
                0.9,
                heading_path=("Documentation", "Rate limits"),
                access_labels=("docs",),
            ),
        ]
        self.retrieval = RagRetrievalService(
            EvaluationRepository(self.chunks)
        )
        self.observer = _RecordingObserver()
        self.answer_service = RagAnswerService(
            self.retrieval,
            observer=self.observer,
        )

    async def test_golden_questions_meet_retrieval_quality_targets(self) -> None:
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

        recalls = []
        precisions = []
        reciprocal_ranks = []

        for case in golden:
            answer = await self.answer_service.answer(
                query=case["question"],
                limit=LIMIT,
                access_labels=tuple(case["access_labels"]),
                owner_identity=case["owner_identity"],
            )

            retrieved_ids = [
                chunk.chunk_id
                for chunk in answer.retrieved_chunks
            ]
            expected_ids = set(case["expected_chunk_ids"])

            recalls.append(recall_at_k(expected_ids, retrieved_ids))
            precisions.append(precision_at_k(expected_ids, retrieved_ids))

            # MRR is defined over queries with at least one relevant result.
            # No-answer and access-denial cases are evaluated through the
            # insufficient-evidence assertion below.
            if expected_ids:
                reciprocal_ranks.append(
                    reciprocal_rank(expected_ids, retrieved_ids)
                )

            self.assertEqual(
                set(expected_ids),
                set(expected_ids) & set(retrieved_ids),
                f"Missing expected evidence for: {case['question']}",
            )

            for expected_text in case["expected_answer_contains"]:
                self.assertIn(
                    expected_text,
                    answer.answer,
                    f"Answer does not contain expected evidence for: {case['question']}",
                )

            if expected_ids:
                self.assertTrue(answer.citations)
                for citation in answer.citations:
                    self.assertIn(citation.chunk_id, retrieved_ids)
                self.assertIsNone(self.observer.events[-1].abstention_reason)
            else:
                self.assertTrue(answer.insufficient_evidence)
                self.assertEqual(answer.citations, ())
                self.assertIn(
                    self.observer.events[-1].abstention_reason,
                    ("no_chunks", "below_term_threshold"),
                )

        self.assertGreaterEqual(sum(recalls) / len(recalls), 0.9)
        self.assertGreaterEqual(sum(precisions) / len(precisions), 0.8)
        self.assertGreaterEqual(
            sum(reciprocal_ranks) / len(reciprocal_ranks),
            0.9,
        )

    async def test_no_evidence_returns_insufficient_evidence(self) -> None:
        answer = await self.answer_service.answer(
            query="completely unrelated query",
            access_labels=("public",),
        )

        self.assertTrue(answer.insufficient_evidence)
        self.assertEqual(answer.answer, "")
        self.assertEqual(answer.citations, ())


if __name__ == "__main__":
    unittest.main(verbosity=2)

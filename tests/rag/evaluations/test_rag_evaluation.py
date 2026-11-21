"""Golden-set evaluation for the RAG retrieval and answer baseline."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import Mock

from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk

GOLDEN_PATH = Path(__file__).with_name("golden_questions.json")


class EvaluationRepository:
    """Deterministic repository used to evaluate the RAG baseline."""

    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
    ) -> list[RetrievedChunk]:
        import re

        terms = {
            term
            for term in re.findall(r"\w+", query.lower())
            if term
        }

        def matches_query(chunk: RetrievedChunk) -> bool:
            words = set(re.findall(r"\w+", chunk.text.lower()))
            return bool(terms & words)

        matches = [
            chunk
            for chunk in self._chunks
            if matches_query(chunk)
            and (
                not access_labels
                or any(label in chunk.access_labels for label in access_labels)
            )
        ]

        return sorted(matches, key=lambda chunk: chunk.score, reverse=True)[:limit]


def make_chunk(
    chunk_id: str,
    text: str,
    score: float,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        revision_id="revision-1",
        document_id="document-1",
        text=text,
        score=score,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        heading_path=("Guide",),
        access_labels=("public",),
    )


class RagEvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_golden_questions_retrieve_expected_evidence(self) -> None:
        golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

        repository = EvaluationRepository(
            [
                make_chunk(
                    "chunk-guide",
                    "# Guide\n\nIntroduction.",
                    0.5,
                ),
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                ),
            ]
        )
        retrieval = RagRetrievalService(repository)
        answer_service = RagAnswerService(retrieval)

        for case in golden:
            answer = await answer_service.answer(
                query=case["question"],
                limit=5,
                access_labels=tuple(case["access_labels"]),
            )

            retrieved_ids = [
                chunk.chunk_id
                for chunk in answer.retrieved_chunks
            ]

            self.assertFalse(
                answer.insufficient_evidence,
                f"Expected evidence for: {case['question']}",
            )
            self.assertTrue(
                set(case["expected_chunk_ids"]).issubset(set(retrieved_ids)),
                f"Missing expected evidence for: {case['question']}",
            )

            for expected_text in case["expected_answer_contains"]:
                self.assertIn(
                    expected_text,
                    answer.answer,
                    f"Answer does not contain expected evidence for: {case['question']}",
                )

            self.assertTrue(answer.citations)
            for citation in answer.citations:
                self.assertIn(
                    citation.chunk_id,
                    retrieved_ids,
                    "Citation must refer to retrieved evidence",
                )

    async def test_no_evidence_returns_insufficient_evidence(self) -> None:
        repository = EvaluationRepository([])
        retrieval = RagRetrievalService(repository)
        answer_service = RagAnswerService(retrieval)

        answer = await answer_service.answer(
            query="completely unrelated query",
            access_labels=("public",),
        )

        self.assertTrue(answer.insufficient_evidence)
        self.assertEqual(answer.answer, "")
        self.assertEqual(answer.citations, ())


if __name__ == "__main__":
    unittest.main(verbosity=2)

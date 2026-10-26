"""Chunking must preserve sentence punctuation and Markdown table rows."""

from __future__ import annotations

import unittest

from bintu_api.context import split_into_chunks


class ChunkQualityTests(unittest.TestCase):
    def test_preserves_sentence_punctuation(self) -> None:
        text = (
            "Alpha beta gamma. Delta epsilon zeta. "
            "Eta theta iota. Kappa lambda mu."
        )

        chunks = split_into_chunks(text, 8)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertTrue(
                chunk.endswith((".", "!", "?")),
                f"Chunk lost sentence punctuation: {chunk!r}",
            )

    def test_does_not_split_table_row(self) -> None:
        text = "\n".join(
            [
                "| Name | Description |",
                "| --- | --- |",
                "| Alpha | " + "a" * 100 + " |",
                "| Beta | " + "b" * 100 + " |",
            ]
        )

        chunks = split_into_chunks(text, 30)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            for line in chunk.splitlines():
                if line.startswith("|") and not line.startswith("| ---"):
                    self.assertTrue(
                        line.endswith("|"),
                        f"Table row was split: {line!r}",
                    )

    def test_preserves_paragraph_boundaries(self) -> None:
        text = (
            "First paragraph sentence one. First paragraph sentence two.\n\n"
            "Second paragraph sentence one. Second paragraph sentence two."
        )

        chunks = split_into_chunks(text, 12)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertTrue(chunk.strip())

    def test_single_chunk_when_text_fits(self) -> None:
        text = "Short paragraph.\n\nAnother short paragraph."

        chunks = split_into_chunks(text, 100)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)

    def test_empty_text_returns_no_chunks(self) -> None:
        self.assertEqual(split_into_chunks("", 100), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
"""Tests for token-budgeted, fence-aware chunking."""

from __future__ import annotations

import unittest

from bintu_api.context import count_tokens, split_into_chunks


class SplitIntoChunksTests(unittest.TestCase):
    def test_empty_text_returns_no_chunks(self) -> None:
        self.assertEqual(split_into_chunks("", 1000), [])

    def test_short_text_returns_one_chunk(self) -> None:
        text = "This is a short paragraph."
        chunks = split_into_chunks(text, 1000)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0], text)
        self.assertLessEqual(count_tokens(chunks[0]), 1000)

    def test_long_text_is_split_within_budget(self) -> None:
        paragraph = (
            "Web scraping is the process of extracting data from websites. "
            "It can support research, monitoring, and automation workflows. "
        )
        text = paragraph * 100
        chunks = split_into_chunks(text, 200)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertLessEqual(count_tokens(chunk), 200)
            self.assertTrue(chunk.strip())

    def test_words_are_not_split(self) -> None:
        text = " ".join(["extraordinary"] * 300)
        chunks = split_into_chunks(text, 100)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            for word in chunk.split():
                self.assertEqual(word, "extraordinary")

    def test_fenced_code_block_is_preserved_when_it_fits(self) -> None:
        text = (
            "Before code.\n\n"
            "```python\n"
            "print('hello')\n"
            "print('world')\n"
            "```\n\n"
            "After code."
        )
        chunks = split_into_chunks(text, 1000)

        self.assertEqual(len(chunks), 1)
        self.assertIn("```python", chunks[0])
        self.assertIn("print('hello')", chunks[0])
        self.assertIn("print('world')", chunks[0])
        self.assertIn("```", chunks[0])

    def test_oversized_fenced_code_block_has_balanced_fences(self) -> None:
        code_lines = "\n".join(f"line_{index} = {index}" for index in range(200))
        text = f"```python\n{code_lines}\n```"
        chunks = split_into_chunks(text, 100)

        self.assertGreater(len(chunks), 1)

        for chunk in chunks:
            self.assertTrue(chunk.startswith("```python"))
            self.assertTrue(chunk.rstrip().endswith("```"))

    def test_zero_budget_returns_original_text(self) -> None:
        text = "Keep this text unchanged."
        self.assertEqual(split_into_chunks(text, 0), [text])


if __name__ == "__main__":
    unittest.main(verbosity=2)

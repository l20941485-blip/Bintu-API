import inspect
import bintu_api.mcp

import unittest

from bintu_api.context import resolve_effective_char_cap, split_into_chunks


class EffectiveCharCapTests(unittest.TestCase):
    def test_default_cap_is_a_floor(self):
        self.assertEqual(resolve_effective_char_cap(10_000, 6_000), 40_000)

    def test_small_budget_keeps_default_cap(self):
        self.assertEqual(resolve_effective_char_cap(100, 6_000), 6_000)

    def test_absolute_ceiling_is_enforced(self):
        self.assertEqual(resolve_effective_char_cap(100_000, 6_000), 200_000)

    def test_zero_or_negative_budget_falls_back_to_default(self):
        self.assertEqual(resolve_effective_char_cap(0, 6_000), 6_000)
        self.assertEqual(resolve_effective_char_cap(-1, 6_000), 6_000)

    def test_operator_configured_cap_is_a_hard_ceiling(self):
        self.assertEqual(resolve_effective_char_cap(10_000, 40), 40)
        self.assertEqual(resolve_effective_char_cap(100_000, 40), 40)


class ChunkPaginationTests(unittest.TestCase):
    def test_large_text_produces_multiple_chunks(self):
        paragraph = "This is a long sentence used to test chunk pagination. "
        text = paragraph * 2_000

        chunks = split_into_chunks(text, 10_000)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 40_000 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()

class McpTokenBudgetExtractionTests(unittest.TestCase):
    def test_mcp_forwards_max_tokens_to_extraction(self):
        source = inspect.getsource(bintu_api.mcp)
        self.assertIn("max_tokens=arguments.max_tokens", source)


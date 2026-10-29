from bintu_api.extraction_quality import (
    dedupe_blocks,
    normalize_markdown,
    truncate_to_token_budget,
)


def test_truncation_closes_cut_code_fence():
    text = "```python\nprint('one')\nprint('two')\nprint('three')\n```"
    result, truncated = truncate_to_token_budget(text, 5)

    assert truncated is True
    assert result.count("```") % 2 == 0


def test_normalize_markdown_leaves_code_fence_alone():
    text = "Before\n```python\nprint('a') # note\n```\nAfter"
    result = normalize_markdown(text)

    assert "print('a') # note" in result


def test_dedupe_does_not_treat_python_comment_as_heading():
    text = "```python\n# comment\nprint('a')\n```\n# Real Heading\nBody"
    result, removed = dedupe_blocks(text)

    assert removed == 0
    assert "# Real Heading" in result

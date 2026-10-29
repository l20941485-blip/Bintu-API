"""Tests for balanced Markdown code fences during bounded chunking."""

from bintu_api.context import count_tokens, split_into_chunks



def test_small_code_fence_stays_atomic():
    text = "Intro paragraph.\n\n```python\nprint('one')\nprint('two')\n```\n\nClosing paragraph."
    chunks = split_into_chunks(text, 1000)


    assert len(chunks) == 1
    assert chunks[0].count("```") % 2 == 0



def test_large_code_fence_produces_balanced_chunks():
    code_lines = [f"print('line {number}')" for number in range(200)]
    text = "```python\n" + "\n".join(code_lines) + "\n```"
    chunks = split_into_chunks(text, 100)


    assert len(chunks) > 1
    for chunk in chunks:
        assert count_tokens(chunk) <= 100
        assert chunk.count("```") % 2 == 0
        assert chunk.lstrip().startswith("```python")
        assert chunk.rstrip().endswith("```")



def test_code_and_prose_do_not_lose_fence_balance():
    text = (
        "Paragraph one.\n\n"
        "```python\n"
        + "\n".join(f"print('line {number}')" for number in range(150))
        + "\n```\n\n"
        "Paragraph two."
    )
    chunks = split_into_chunks(text, 100)


    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.count("```") % 2 == 0
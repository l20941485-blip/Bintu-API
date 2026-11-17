import pytest

from bintu_api.extraction.rag_chunking import (
    CHUNKER_VERSION,
    make_chunk_id,
    split_semantic_chunks,
)


def test_heading_inside_code_fence_is_not_a_section_boundary():
    markdown = """# Guide

```python
# This is not a Markdown heading
print("hello")
```

## Authentication

Use an API key.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=200)

    assert len(chunks) == 2
    assert chunks[0].text.startswith("# Guide")
    assert chunks[1].text.startswith("## Authentication")


def test_heading_path_resets_when_returning_to_parent_section():
    markdown = """# Bintu API

## Authentication

### API keys

Use an API key.

## Rate limits

Requests are limited.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=200)

    assert chunks[1].heading_path == ["Bintu API", "Authentication"]
    assert chunks[2].heading_path == [
        "Bintu API",
        "Authentication",
        "API keys",
    ]
    assert chunks[3].heading_path == ["Bintu API", "Rate limits"]


def test_repeated_headings_use_their_actual_positions():
    markdown = """# Guide

First guide.

## Authentication

First authentication section.

# Guide

Second guide.

## Authentication

Second authentication section.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=200)

    authentication_chunks = [chunk for chunk in chunks if chunk.heading_path[-1] == "Authentication"]

    assert len(authentication_chunks) == 2
    assert authentication_chunks[0].text.startswith("## Authentication")
    assert authentication_chunks[1].text.startswith("## Authentication")
    assert authentication_chunks[0].text != authentication_chunks[1].text


def test_overlap_uses_previous_suffix_and_respects_budget():
    markdown = """## Section

Paragraph one with enough content to require splitting.

Paragraph two with enough content to require splitting.
"""

    chunks = split_semantic_chunks(
        markdown,
        max_tokens=20,
        overlap_tokens=5,
    )

    assert len(chunks) > 1

    for index in range(1, len(chunks)):
        previous = chunks[index - 1].text
        current = chunks[index].text

        previous_words = previous.split()
        overlap_words = current.split()[: len(previous_words)]

        assert any(word in current for word in previous_words[-3:])
        assert chunks[index].approx_tokens <= 20


def test_chunk_id_changes_with_chunking_options():
    base = make_chunk_id(
        source_url="https://example.com/docs",
        content_sha256="abc",
        chunk_strategy="semantic",
        chunk_index=0,
    )

    different_budget = make_chunk_id(
        source_url="https://example.com/docs",
        content_sha256="abc",
        chunk_strategy="semantic",
        chunk_index=0,
        max_tokens=500,
    )

    different_overlap = make_chunk_id(
        source_url="https://example.com/docs",
        content_sha256="abc",
        chunk_strategy="semantic",
        chunk_index=0,
        max_tokens=500,
        overlap_tokens=50,
    )

    assert base != different_budget
    assert different_budget != different_overlap


def test_oversized_url_is_not_split():
    url = "https://example.org/" + ("a" * 120)
    markdown = f"Before {url} after"

    chunks = split_semantic_chunks(markdown, max_tokens=8)

    matching = [chunk for chunk in chunks if url in chunk.text]
    assert len(matching) == 1
    assert matching[0].text.count(url) == 1


def test_fitting_code_fence_remains_atomic():
    markdown = """## Example

```python
print("hello")
```
"""

    chunks = split_semantic_chunks(markdown, max_tokens=100)

    assert len(chunks) == 1
    assert "```python" in chunks[0].text
    assert 'print("hello")' in chunks[0].text
    assert chunks[0].text.rstrip().endswith("```")


def test_fitting_table_remains_atomic():
    markdown = """## Supported modes

| Mode | Purpose |
| --- | --- |
| scrape | Readable text |
| chunk | Retrieval chunks |
"""

    chunks = split_semantic_chunks(markdown, max_tokens=100)

    assert len(chunks) == 1
    assert "| Mode | Purpose |" in chunks[0].text
    assert "| chunk | Retrieval chunks |" in chunks[0].text


def test_overlap_must_be_less_than_budget():
    with pytest.raises(ValueError):
        split_semantic_chunks(
            "text",
            max_tokens=100,
            overlap_tokens=100,
        )


def test_empty_text_returns_no_chunks():
    assert split_semantic_chunks("", max_tokens=100) == []
    assert split_semantic_chunks("   \n  ", max_tokens=100) == []


def test_existing_public_contract_remains_compatible():
    markdown = """# Bintu API

## Authentication

Use an API key.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=100)

    assert chunks[0].index == 0
    assert chunks[0].chunk_strategy == "semantic"
    assert chunks[0].approx_tokens == chunks[0].tokens
    assert chunks[0].chunk_id.startswith("sha256:")
    assert CHUNKER_VERSION


def test_long_paragraph_prefers_sentence_boundaries():
    text = (
        "# Guide\n\n"
        + ("First sentence. " * 30)
        + ("Second sentence. " * 30)
    )

    chunks = split_semantic_chunks(text, max_tokens=100)

    assert len(chunks) > 1

    prose_chunks = [
        chunk
        for chunk in chunks[:-1]
        if not all(line.lstrip().startswith("#") for line in chunk.text.splitlines() if line.strip())
    ]

    assert prose_chunks

    for chunk in prose_chunks:
        stripped = chunk.text.rstrip()
        assert stripped.endswith((".", "!", "?")), stripped[-40:]

    for chunk in chunks:
        assert chunk.text.strip()
        assert not chunk.text.startswith("entence")
        assert not chunk.text.endswith("First sent")

def test_url_fragments_do_not_cross_chunk_boundaries():
    url = "https://example.org/" + ("a" * 120)
    markdown = f"Before {url} after"

    chunks = split_semantic_chunks(markdown, max_tokens=8)

    for chunk in chunks:
        assert not chunk.text.startswith("://")
        assert not chunk.text.startswith("example.org/")
        assert not chunk.text.endswith("https:")
        assert not chunk.text.endswith("example.org/")

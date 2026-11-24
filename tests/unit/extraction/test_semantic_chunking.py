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


def test_single_oversized_sentence_falls_back_to_whitespace():
    text = " ".join(["ordinary"] * 120) + "."

    chunks = split_semantic_chunks(text, max_tokens=100)

    assert len(chunks) > 1
    assert all(chunk.approx_tokens <= 100 for chunk in chunks)


# =============================================================================
# PROVENANCE & STABILITY TESTS (Stage 8: Chunk Provenance)
# =============================================================================

def test_chunk_content_hash_is_per_chunk_not_document():
    """Verify content_sha256 is the hash of the chunk text, not the document."""
    import hashlib
    
    markdown = "# Intro\n\nFirst paragraph.\n\n## Section\n\nSecond paragraph."
    doc_hash = "this_is_the_document_hash_12345"
    
    chunks = split_semantic_chunks(
        markdown,
        max_tokens=20,
        source_url="https://example.com/doc",
        content_sha256=doc_hash, # Pass the document hash
    )
    
    assert len(chunks) > 1
    
    for chunk in chunks:
        # The chunk's content_sha256 should NOT be the document hash
        assert chunk.content_sha256 != doc_hash, \
            f"Chunk {chunk.index} incorrectly uses document hash!"
        
        # It SHOULD be the SHA-256 of its own text
        expected = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        assert chunk.content_sha256 == expected, \
            f"Chunk {chunk.index} hash mismatch: got {chunk.content_sha256}, expected {expected}"


def test_chunk_id_stability_with_unrelated_changes():
    """Changing later sections must not change earlier chunk IDs."""
    base_text = "# Title\n\nIntro content here.\n\n## Section A\n\nContent of A."
    modified_text = base_text + "\n\n## Section B\n\nAdded new section B at the end."
    
    chunks_base = split_semantic_chunks(base_text, max_tokens=50, source_url="https://ex.com", content_sha256="hash")
    chunks_mod = split_semantic_chunks(modified_text, max_tokens=50, source_url="https://ex.com", content_sha256="hash")
    
    # The first chunk (Intro) should have the SAME ID in both versions
    # because its content and position didn't change.
    assert len(chunks_base) >= 1
    assert len(chunks_mod) >= 1
    
    # If we use per-chunk hashing, these match. If we use doc hashing, they differ.
    assert chunks_base[0].chunk_id == chunks_mod[0].chunk_id, \
        f"Chunk ID instability: '{chunks_base[0].chunk_id}' != '{chunks_mod[0].chunk_id}'"


def test_chunk_id_changes_when_chunk_content_changes():
    """Modifying a specific chunk MUST change its ID."""
    original = "# Title\n\nOriginal sentence here."
    modified = "# Title\n\nModified sentence here." # Changed word
    
    chunks_orig = split_semantic_chunks(original, max_tokens=50, source_url="https://ex.com", content_sha256="hash")
    chunks_mod = split_semantic_chunks(modified, max_tokens=50, source_url="https://ex.com", content_sha256="hash")
    
    assert len(chunks_orig) == 1
    assert len(chunks_mod) == 1
    
    assert chunks_orig[0].chunk_id != chunks_mod[0].chunk_id, \
        "Chunk ID did not change when content changed!"


def test_chunk_provenance_fields_completeness():
    """Verify all required schema fields are populated correctly."""
    markdown = "# H1\n\nText content.\n\n## H2\n\nMore text."
    
    chunks = split_semantic_chunks(
        markdown,
        max_tokens=50,
        source_url="https://example.com/test",
        final_url="https://example.com/final",
        content_sha256="dummy_doc_hash",
        extracted_at="2026-11-24T12:00:00Z",
    )
    
    assert len(chunks) > 0
    
    for chunk in chunks:
        # Core identity
        assert isinstance(chunk.index, int) and chunk.index >= 0
        assert chunk.chunk_strategy == "semantic"
        assert chunk.chunk_id.startswith("sha256:")
        assert len(chunk.chunk_id) == 71 # "sha256:" + 64 hex chars
        
        # Content integrity
        assert isinstance(chunk.content_sha256, str) and len(chunk.content_sha256) == 64
        
        # Context/Provenance
        assert chunk.source_url == "https://example.com/test"
        assert chunk.final_url == "https://example.com/final"
        assert chunk.extracted_at == "2026-11-24T12:00:00Z"
        
        # Structure
        assert isinstance(chunk.heading_path, list)
        assert isinstance(chunk.section_index, int)

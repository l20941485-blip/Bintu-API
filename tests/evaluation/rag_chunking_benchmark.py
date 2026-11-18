"""Public, deterministic RAG chunking evaluation suite.

These checks validate retrieval-oriented chunk guarantees. They establish
observable engineering properties; they do not claim that Bintu is the best
RAG chunker or measure end-to-end retrieval quality.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass

from bintu_api.extraction.rag_chunking import (
    CHUNKER_VERSION,
    make_chunk_id,
    split_semantic_chunks,
)


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    markdown: str
    max_tokens: int
    overlap_tokens: int = 0
    source_url: str = "https://example.com/benchmark"


HEADING_CASE = BenchmarkCase(
    name="heading_preservation",
    markdown="""# API Guide

## Authentication

Use an API key for authenticated requests.

## Rate limits

Requests are limited per API key.
""",
    max_tokens=100,
)

TABLE_CASE = BenchmarkCase(
    name="atomic_small_table",
    markdown="""# Release notes

## Changes

| Version | Change |
| --- | --- |
| 1.0 | Initial release |
| 1.1 | Added chunk metadata |
""",
    max_tokens=100,
)

CODE_CASE = BenchmarkCase(
    name="atomic_code_block",
    markdown="""# SDK usage

```python
client = BintuClient(api_key="test")
result = client.scrape("[https://example.com](https://example.com)")
print(result.text)
```

Use the returned text in downstream applications.
""",
    max_tokens=100,
)

CONTEXT_CASE = BenchmarkCase(
    name="context_independence",
    markdown="""# Deployment guide

## Render deployment

Deploy the latest main branch and verify the health endpoint.
""",
    max_tokens=100,
)

OVERSIZED_CASE = BenchmarkCase(
    name="oversized_section_overlap",
    markdown=(
        "# Long section\n\n"
        + "\n\n".join(
            f"Sentence {number} provides independent retrieval context."
            for number in range(1, 25)
        )
    ),
    max_tokens=40,
    overlap_tokens=8,
)


def run_case(case: BenchmarkCase):
    content_sha256 = hashlib.sha256(
        case.markdown.encode("utf-8")
    ).hexdigest()

    return split_semantic_chunks(
        case.markdown,
        max_tokens=case.max_tokens,
        overlap_tokens=case.overlap_tokens,
        source_url=case.source_url,
        content_sha256=content_sha256,
    )


def assert_heading_preservation(chunks):
    assert chunks
    assert any(
        "Authentication" in chunk.heading_path
        for chunk in chunks
    ), "A chunk from the Authentication section must retain its heading path"


def assert_atomic_table(chunks):
    table_chunks = [
        chunk for chunk in chunks
        if "| Version |" in chunk.text
    ]
    assert len(table_chunks) == 1
    assert table_chunks[0].contains_table is True
    assert "| 1.1 |" in table_chunks[0].text


def assert_atomic_code(chunks):
    code_chunks = [
        chunk for chunk in chunks
        if "```python" in chunk.text
    ]
    assert len(code_chunks) == 1
    assert code_chunks[0].contains_code is True
    assert 'print(result.text)' in code_chunks[0].text


def assert_context_independence():
    markdown = CONTEXT_CASE.markdown
    content_sha256 = hashlib.sha256(markdown.encode("utf-8")).hexdigest()

    first = make_chunk_id(
        source_url="https://example.com/deployment",
        content_sha256=content_sha256,
        chunk_strategy="semantic",
        chunk_index=0,
    )
    second = make_chunk_id(
        source_url="https://example.com/alternate",
        content_sha256=content_sha256,
        chunk_strategy="semantic",
        chunk_index=0,
    )

    assert first != second

    chunks = run_case(CONTEXT_CASE)
    section_chunks = [
        chunk
        for chunk in chunks
        if "Render deployment" in chunk.heading_path
    ]

    assert section_chunks
    assert section_chunks[0].heading_path == [
        "Deployment guide",
        "Render deployment",
    ]
    assert section_chunks[0].section_index == 1


def assert_determinism(case: BenchmarkCase):
    first = run_case(case)
    second = run_case(case)

    assert first == second
    assert [chunk.chunk_id for chunk in first] == [
        chunk.chunk_id for chunk in second
    ]


def assert_token_budget(case: BenchmarkCase):
    for chunk in run_case(case):
        assert chunk.approx_tokens <= case.max_tokens


def assert_overlap_correctness(case: BenchmarkCase):
    chunks = run_case(case)
    assert len(chunks) > 1

    for previous, current in itertools.pairwise(chunks):
        previous_words = previous.text.split()
        current_words = current.text.split()
        overlap = set(previous_words) & set(current_words)
        assert overlap, "Oversized sections should retain deterministic overlap"


def assert_freshness():
    original = run_case(HEADING_CASE)
    updated_markdown = HEADING_CASE.markdown.replace(
        "Requests are limited per API key.",
        "Requests are limited per API key and region.",
    )

    updated = run_case(
        BenchmarkCase(
            name="freshness",
            markdown=updated_markdown,
            max_tokens=HEADING_CASE.max_tokens,
        )
    )

    original_hash = hashlib.sha256(
        HEADING_CASE.markdown.encode("utf-8")
    ).hexdigest()
    updated_hash = hashlib.sha256(
        updated_markdown.encode("utf-8")
    ).hexdigest()

    assert original_hash != updated_hash
    assert [chunk.chunk_id for chunk in original] != [
        chunk.chunk_id for chunk in updated
    ]


def run_benchmarks():
    assert CHUNKER_VERSION

    assert_heading_preservation(run_case(HEADING_CASE))
    assert_atomic_table(run_case(TABLE_CASE))
    assert_atomic_code(run_case(CODE_CASE))
    assert_context_independence()
    assert_determinism(HEADING_CASE)
    assert_token_budget(HEADING_CASE)
    assert_token_budget(TABLE_CASE)
    assert_token_budget(CODE_CASE)
    assert_token_budget(OVERSIZED_CASE)
    assert_overlap_correctness(OVERSIZED_CASE)
    assert_freshness()

# Chunking contract audit

## Purpose

This audit establishes the current Bintu chunking baseline before adding
heading paths, stable identifiers, RAG controls, structured-content handling,
or expanded provenance.

## Scope

Audit the following surfaces:

- REST extraction and context/chunk endpoints.
- MCP schemas, aliases, and handlers.
- Sequential and semantic chunking implementations.
- Section selection and main-content cleaning.
- Fresh, memory-hit, and persistent-hit responses.
- Existing metadata, overlap, identifiers, and provenance.

## Feature inventory

For each item, record:

| Feature | Status | Implementation | Public surfaces | Defaults | Tests | Gaps |
|---|---|---|---|---|---|---|
| `chunk_strategy` | Absent / partial / complete |  |  |  |  |  |
| `overlap_tokens` | Absent / partial / complete |  |  |  |  |  |
| `heading_path` | Absent / partial / complete |  |  |  |  |  |
| `section_index` | Absent / partial / complete |  |  |  |  |  |
| Stable `chunk_id` | Absent / partial / complete |  |  |  |  |  |
| Heading-aware boundaries | Absent / partial / complete |  |  |  |  |  |
| Paragraph boundaries | Absent / partial / complete |  |  |  |  |  |
| Sentence boundaries | Absent / partial / complete |  |  |  |  |  |
| `include_heading_path` | Absent / partial / complete |  |  |  |  |  |
| `include_page_context` | Absent / partial / complete |  |  |  |  |  |
| `return_metadata` | Absent / partial / complete |  |  |  |  |  |
| List preservation | Absent / partial / complete |  |  |  |  |  |
| Table preservation | Absent / partial / complete |  |  |  |  |  |
| Code-block preservation | Absent / partial / complete |  |  |  |  |  |
| Image alt text | Absent / partial / complete |  |  |  |  |  |
| Source anchors | Absent / partial / complete |  |  |  |  |  |
| Provenance fields | Absent / partial / complete |  |  |  |  |  |

## Processing order

Document the actual current order:

1. Fetch and validate.
2. Extract canonical content.
3. Apply content cleaning.
4. Select requested sections.
5. Apply chunking.
6. Apply overlap and context prefixes.
7. Build metadata and response.

State explicitly whether section filtering currently occurs before chunking,
and whether overlap can reintroduce excluded content.

## Semantics to define

Document the following before implementation:

- `section_index`: source-document ordering versus filtered-response ordering.
- `chunk_id`: exact inputs, determinism guarantees, and versioning.
- Token counting: exact tokenizer count versus approximation.
- `include_heading_path`: metadata-only versus injected text prefix.
- `include_page_context`: deterministic source context versus generated content.
- `return_metadata`: optional enrichment versus required provenance.
- Oversized units: URLs, words, tables, code blocks, and list items.

## Compatibility constraints

Record:

- Existing REST and MCP contracts.
- Existing defaults that must not change silently.
- Cache-hit versus fresh-response differences.
- Token accounting and savings behavior.
- Security and URL-redaction requirements.

## Verification

Record the exact commands run and their results.

## Findings

Fill this section only after inspecting the code and tests.

## Recommended next changes

Prioritize changes by impact, effort, and compatibility risk.

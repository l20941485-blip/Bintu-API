# Chunk location provenance

Chunk location provenance identifies where a returned chunk occurred in the
source text used for chunking.

## Fields

| Field | Meaning |
|---|---|
| `heading_path` | Hierarchical Markdown headings containing the chunk. |
| `char_start` | Zero-based character offset of the chunk in the chunking source text. |
| `char_end` | Exclusive character offset of the chunk in the chunking source text. |
| `reassembled` | `true` when a reliable source location could not be determined. |

## Source text

Offsets refer to the text after link policy is applied, immediately before
chunking. They do not necessarily refer to the original fetched HTML or to a
different link-policy setting.

## Unknown locations

When `reassembled` is `true`, `char_start` and `char_end` are `null`.

This occurs when chunk normalization or lead-in handling prevents an exact
match in the source text. Bintu does not return approximate offsets in that
case, because an incorrect location is worse than an explicitly unknown one.

## Strategy behavior

Sequential chunks receive a derived heading path when one can be determined.
Semantic chunks retain their section-derived heading path. Both strategies
receive offsets when their delivered text can be located exactly.

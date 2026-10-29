import re

from bintu_api import context_baseline as old
from bintu_api import context_chunking as new

try:
    import pytest
except ImportError:  # tiny stand-in so the file also runs without pytest
    pytest = None

count = new.count_tokens

IANA = """# IANA-managed Reserved Domains
Certain domains are set aside, and nominally registered to \u201cIANA\u201d, for specific policy or technical purposes.
## Example domains
As described in RFC 2606 (https://www.iana.org/go/rfc2606) and RFC 6761 (https://www.iana.org/go/rfc6761), a number of domains such as example.com and example.org are maintained for documentation purposes. These domains may be used as illustrative examples in documents without prior coordination with us. They are not available for registration or transfer.
## Test IDN top-level domains
These domains were temporarily delegated by IANA for the IDN Evaluation (http://www.icann.org/topics/idn/) being conducted by ICANN (http://www.icann.org/).
Domain | Domain (A-label) | Language | Script
--- | --- | --- | ---
\u0625\u062e\u062a\u0628\u0627\u0631 | xn--kgbechtv | Arabic | Arabic
\u6d4b\u8bd5 | xn--0zwm56d | Chinese | Han (Simplified variant)
\u0438\u0441\u043f\u044b\u0442\u0430\u043d\u0438\u0435 | xn--80akhbyknj4f | Russian | Cyrillic
## Policy-reserved domains
We act as both the registrant and registrar for a select number of domains which have been reserved under policy grounds. These exclusions are typically indicated in either technical standards (RFC documents), or contractual limitations (http://www.icann.org/en/registries/agreements.htm)."""

DOCS = """# json \u2014 JSON encoder and decoder
This module exposes an API familiar to users of the standard library.
Encoding basic Python object hierarchies:
```python3
>>> import json
>>> json.dumps(['foo', {'bar': ('baz', None, 1.0, 2)}])
>>> def custom_json(obj):
...     if isinstance(obj, complex):
...         return {'real': obj.real}
```
Compact encoding:
```python3
>>> json.dumps([1, 2, 3], separators=(',', ':'))
```
## Command-line interface
Using json from the shell:
```shell-session
$ echo '{"json":"obj"}' | python -m json
{
    "json": "obj"
}
$ echo '{1.2:3.4}' | python -m json
Expecting property name enclosed in double quotes
```
Changed in version 3.5. The output is now in the same order as the input."""


def fences_balanced(text):
    return sum(1 for line in text.split("\n") if line.startswith("```")) % 2 == 0


# ---- summarize ------------------------------------------------------------


def test_old_summarize_reproduces_example_dot_space_org():
    out = old.baseline_summarize(IANA, 250)
    assert "example. org" in out and "icann. org" in out
    assert "purposes. ## Example domains" in out


def test_new_summarize_keeps_domains_and_headings():
    out, truncated = new.summarize_text(IANA, 250)
    assert truncated is True
    assert "example. org" not in out and "icann. org" not in out
    assert "example.org" in out
    assert "purposes.\n## Example domains\n" in out
    assert count(out) <= 250


def test_summarize_returns_text_unchanged_when_it_fits():
    assert new.summarize_text("Short text.", 100) == ("Short text.", False)


def test_summarize_never_ends_on_a_heading():
    text = "Intro line here.\n## Heading With Nothing Under It\n" + "word " * 400
    out, _ = new.summarize_text(text, 20)
    assert not re.match(r"^#{1,6}\s", out.split("\n")[-1])


def test_summarize_keeps_fences_atomic_and_closed():
    for budget in (30, 60, 100, 150, 300):
        out, _ = new.summarize_text(DOCS, budget)
        assert count(out) <= budget
        assert fences_balanced(out)


def test_summarize_single_huge_line_falls_back_to_hard_cut():
    out, truncated = new.summarize_text("x" * 5000, 50)
    assert truncated and count(out) <= 50 and out.endswith("\u2026")


def test_summarize_whole_sentences_at_the_cut():
    text = "First sentence is here. Second sentence is here too. " + "More words follow here. " * 50
    out, _ = new.summarize_text(text, 25)
    assert out.endswith(".") and count(out) <= 25


# ---- chunking -------------------------------------------------------------


def test_old_chunking_glues_heading_and_adds_blank_lines():
    glued = "\n".join(old.split_into_chunks(IANA, 150))
    assert "purposes. ## Example domains" in glued
    fenced = "\n".join(old.split_into_chunks(DOCS, 400))
    assert "\n\n\n```" in fenced


def test_new_chunking_preserves_heading_lines():
    chunks = new.split_into_chunks(IANA, 150)
    joined = "\n".join(chunks)
    assert "purposes. ## " not in joined
    assert "purposes.\n## Example domains" in joined or any(c.startswith("## Example domains") for c in chunks)
    assert "example.org" in joined


def test_new_chunking_has_no_blank_lines_or_leading_newlines():
    for budget in (60, 150, 400, 2000):
        for chunk in new.split_into_chunks(DOCS, budget):
            assert not chunk.startswith("\n") and not chunk.endswith("\n")
            assert "\n\n" not in chunk


def test_every_chunk_is_within_budget_and_fences_balanced():
    for text in (IANA, DOCS, DOCS * 6):
        for budget in (100, 150, 250, 500, 2000):
            for chunk in new.split_into_chunks(text, budget):
                assert count(chunk) <= budget, (budget, count(chunk))
                assert fences_balanced(chunk)


def test_no_words_are_lost_when_nothing_is_oversized():
    chunks = new.split_into_chunks(IANA, 150)
    squash = lambda s: re.sub(r"\s+", " ", s).strip()
    assert squash("\n".join(chunks)) == squash(IANA)


def test_oversized_code_fence_is_split_by_lines_not_sentences():
    # Lines ending in "." look like sentence boundaries to the old splitter.
    code = "\n".join(f"value_{i} = compute(a, b, c)  # step {i}." for i in range(60))
    text = f"```python\n{code}\n```"

    old_lines = [l for c in old.split_into_chunks(text, 80) for l in c.split("\n")]
    assert any(line.count("value_") > 1 for line in old_lines)  # old: lines re-joined with spaces

    new_chunks = new.split_into_chunks(text, 80)
    for chunk in new_chunks:
        assert fences_balanced(chunk) and count(chunk) <= 80
    rebuilt = [l for c in new_chunks for l in c.split("\n")[1:-1]]
    assert rebuilt == code.split("\n")  # every line intact, in order


def test_heading_is_not_left_at_the_end_of_a_chunk():
    text = "\n".join(
        [f"Paragraph {i} " + "alpha beta gamma delta " * 6 + "\n## Section %d" % i for i in range(12)]
    )
    chunks = new.split_into_chunks(text, 60)
    for chunk in chunks[:-1]:
        lines = chunk.split("\n")
        assert len(lines) == 1 or not re.match(r"^#{1,6}\s", lines[-1])


def test_empty_and_zero_budget():
    assert new.split_into_chunks("", 100) == []
    assert new.split_into_chunks("abc", 0) == ["abc"]


def test_abbreviations_and_initials_do_not_split_sentences():
    pieces = new.sentence_pieces("Dr. Smith met J. Jones in the U.S. office. They talked. Then left.")
    assert pieces == ["Dr. Smith met J. Jones in the U.S. office.", "They talked.", "Then left."]


# ---- table header repetition ----------------------------------------------

TABLE_ROWS = [f"row{i:02d} | value {i} | note for row {i}" for i in range(40)]
TABLE = "Name | Value | Note\n--- | --- | ---\n" + "\n".join(TABLE_ROWS)


def test_split_table_repeats_header_in_every_chunk():
    chunks = new.split_into_chunks(TABLE, 120)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith("Name | Value | Note\n--- | --- | ---\n")
        assert count(chunk) <= 120
    rows = [l for c in chunks for l in c.split("\n")[2:]]
    assert rows == TABLE_ROWS  # every row exactly once, in order


def test_old_chunking_loses_the_header_on_continuation_chunks():
    chunks = old.split_into_chunks(TABLE, 120)
    assert len(chunks) > 1
    assert not chunks[1].startswith("Name | Value | Note")


def test_table_that_fits_is_not_touched():
    small = "A | B\n--- | ---\n1 | 2\n3 | 4"
    assert new.split_into_chunks(small, 500) == [small]


def test_table_without_separator_row_keeps_old_behaviour():
    plain = "\n".join(TABLE_ROWS)
    chunks = new.split_into_chunks(plain, 120)
    assert [l for c in chunks for l in c.split("\n")] == TABLE_ROWS


def test_row_too_big_for_header_plus_row_falls_back_without_header():
    huge = "x | " + "word " * 80
    text = "H1 | H2\n--- | ---\n" + huge + "\nsmall | row"
    chunks = new.split_into_chunks(text, 60)
    assert any(huge.strip() in c for c in chunks)  # row kept whole, nothing lost or raised


def test_header_repetition_inside_a_mixed_document():
    text = IANA_LONG_TABLE = (
        "## Domains\nIntro line here.\n" + TABLE + "\n## After\nClosing paragraph here."
    )
    chunks = new.split_into_chunks(text, 120)
    assert all(count(c) <= 120 for c in chunks)
    table_chunks = [c for c in chunks if "row" in c.split("\n")[0] or c.startswith("Name | Value")]
    assert all(c.startswith("Name | Value | Note\n--- | ---") for c in table_chunks)


# ---- colon-before-fence cohesion ------------------------------------------


def _doc_with_intro(filler_lines):
    filler = "\n".join(f"Filler paragraph {i} " + "lorem ipsum dolor sit amet " * 3 for i in range(filler_lines))
    return filler + "\nFor example:\n```python\nprint('a')\nprint('b')\nprint('c')\n```\nAfter the example."


def _colon_split(chunks):
    return any(
        chunk.split("\n")[-1].rstrip().endswith(":") and chunks[i + 1].startswith("```")
        for i, chunk in enumerate(chunks[:-1])
    )


def test_intro_line_is_not_separated_from_its_fence():
    separated_without_fix = False
    for filler_lines in range(1, 14):
        text = _doc_with_intro(filler_lines)
        without = new.split_into_chunks(text, 90, keep_lead_ins=False)
        separated_without_fix |= _colon_split(without)
        with_fix = new.split_into_chunks(text, 90)
        assert not _colon_split(with_fix), filler_lines
        assert all(count(c) <= 90 and fences_balanced(c) for c in with_fix)
        squash = lambda s: re.sub(r"\s+", " ", s).strip()
        assert squash("\n".join(with_fix)) == squash(text)  # nothing lost or reordered
    assert separated_without_fix  # the test really exercises the bug


def test_heading_then_intro_then_fence_chain_moves_together():
    text = "Filler " * 20 + "\n## Usage\nRun it like this:\n```shell\n$ run --now\n```"
    for budget in (40, 50, 60, 80):
        chunks = new.split_into_chunks(text, budget)
        assert not _colon_split(chunks)
        for chunk in chunks[:-1]:
            assert not re.match(r"^#{1,6}\s", chunk.split("\n")[-1]) or len(chunk.split("\n")) == 1


def test_intro_is_left_alone_when_moving_would_break_the_budget():
    big_fence = "```python\n" + "\n".join(f"line_{i} = {i}" for i in range(20)) + "\n```"
    text = "Some text here.\nFor example:\n" + big_fence
    budget = count(big_fence) + 2  # fence fits alone; fence + intro line does not
    chunks = new.split_into_chunks(text, budget)
    assert all(count(c) <= budget for c in chunks)


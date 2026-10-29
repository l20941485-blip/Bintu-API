from bintu_api.scraper import extract_text_result


def _assert_table_chunks_preserve_content(chunks, expected_lines, header, separator):
    output_lines = [
        line.strip()
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    headers = {header, separator}

    # Only the two header lines may repeat; all other content stays exact.
    assert [
        line for line in output_lines if line not in headers
    ] == [
        line for line in expected_lines if line not in headers
    ]

    assert output_lines.count(header) >= 1
    assert output_lines.count(header) == output_lines.count(separator)

    for chunk in chunks:
        lines = [
            line.strip()
            for line in chunk.splitlines()
            if line.strip()
        ]
        table_lines = [line for line in lines if "|" in line]
        if not table_lines:
            continue

        assert table_lines[:2] == [header, separator]
        assert table_lines.count(header) == 1
        assert table_lines.count(separator) == 1

        header_index = lines.index(header)
        assert lines[header_index + 1] == separator



def test_chunk_mode_preserves_domains_and_urls():
    html = (
        b"<main>"
        b"<p>Visit <a href='https://example.org'>"
        b"example<span>.org</span></a>.</p>"
        b"<p>See <a href='https://example.org/agreements.htm'>"
        b"agreements<span>.htm</span></a>.</p>"
        b"</main>"
    )

    result = extract_text_result(html, 6000)

    assert "example.org" in result.text
    assert "example. org" not in result.text
    assert "agreements.htm" in result.text
    assert "agreements. htm" not in result.text


def test_chunk_mode_preserves_table_rows():
    html = (
        b"<main><table>"
        b"<tr><th>Name</th><th>Value</th></tr>"
        b"<tr><td>Alpha</td><td>1</td></tr>"
        b"<tr><td>Beta</td><td>2</td></tr>"
        b"</table></main>"
    )

    result = extract_text_result(html, 6000)
    lines = result.text.splitlines()

    assert "Name | Value" in lines
    assert "Alpha | 1" in lines
    assert "Beta | 2" in lines


def test_chunk_mode_preserves_paragraph_spacing():
    html = (
        b"<main>"
        b"<p>First paragraph.</p>"
        b"<p>Second paragraph.</p>"
        b"</main>"
    )

    result = extract_text_result(html, 6000)
    lines = result.text.splitlines()

    assert "First paragraph." in lines
    assert "Second paragraph." in lines

def test_actual_chunker_preserves_extracted_table_rows():
    from bintu_api.context import count_tokens, split_into_chunks

    html = (
        b"<main><table>"
        b"<tr><th>Name</th><th>Value</th></tr>"
        b"<tr><td>Alpha</td><td>1</td></tr>"
        b"<tr><td>Beta</td><td>2</td></tr>"
        b"<tr><td>Gamma</td><td>3</td></tr>"
        b"<tr><td>Delta</td><td>4</td></tr>"
        b"</table></main>"
    )
    extracted = extract_text_result(html, 6000).text
    budget = 12

    assert count_tokens(extracted) > budget
    chunks = split_into_chunks(extracted, budget)

    assert len(chunks) > 1
    output_lines = [
        line.strip()
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    expected_lines = [
        line.strip()
        for line in extracted.splitlines()
        if line.strip()
    ]
    _assert_table_chunks_preserve_content(
        chunks, expected_lines, expected_lines[0], expected_lines[1]
    )
    assert all(count_tokens(chunk) <= budget for chunk in chunks)


def test_actual_chunker_preserves_url_when_splitting():
    from bintu_api.context import count_tokens, split_into_chunks

    url = "https://example.org/agreements.htm"
    text = (
        "Read the introduction carefully. "
        f"Visit {url} for the agreement. "
        "Keep a copy for your records."
    )
    budget = 16

    assert count_tokens(text) > budget
    chunks = split_into_chunks(text, budget)

    assert len(chunks) > 1
    assert sum(chunk.count(url) for chunk in chunks) == 1
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split())
    assert all(count_tokens(chunk) <= budget for chunk in chunks)


def test_actual_chunker_preserves_oversized_url():
    from bintu_api.context import count_tokens, split_into_chunks

    url = "https://example.org/" + ("a" * 120)
    budget = 8

    chunks = split_into_chunks(f"Before {url} after", budget)

    assert chunks == ["Before", url, "after"]
    assert count_tokens(url) > budget


def test_actual_chunker_preserves_oversized_table_row():
    from bintu_api.context import count_tokens, split_into_chunks

    row = "VeryLongName" * 10 + " | value"
    text = "Name | Value\n--- | ---\n" + row
    budget = 8

    chunks = split_into_chunks(text, budget)

    assert row in chunks
    assert count_tokens(row) > budget
    assert [
        line
        for chunk in chunks
        for line in chunk.splitlines()
    ] == text.splitlines()


def test_actual_chunker_preserves_table_embedded_in_prose():
    from bintu_api.context import count_tokens, split_into_chunks

    rows = [
        "Domain | Domain (A-label) | Language | Script",
        "--- | --- | --- | ---",
        "alpha | xn--alpha | Example language | Latin",
        "beta | xn--beta | Another language | Greek",
        "gamma | xn--gamma | Third language | Cyrillic",
    ]
    text = (
        "# Reserved domains\n"
        "The following table lists example entries.\n"
        + "\n".join(rows)
        + "\n## Policy\n"
        "These entries are reserved for documentation."
    )
    budget = 30

    chunks = split_into_chunks(text, budget)

    assert len(chunks) > 1
    output_lines = [
        line.strip()
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]

    _assert_table_chunks_preserve_content(
        chunks,
        [line.strip() for line in text.splitlines() if line.strip()],
        rows[0],
        rows[1],
    )

    assert all(count_tokens(chunk) <= budget for chunk in chunks)


def test_actual_chunker_keeps_wide_table_row_intact():
    from bintu_api.context import count_tokens, split_into_chunks

    target_row = (
        "\u03b4\u03bf\u03ba\u03b9\u03bc\u03ae | xn--jxalpdlp"
        " | Greek, Modern (1453-) | Greek"
    )
    rows = [
        "Domain | Domain (A-label) | Language | Script",
        "--- | --- | --- | ---",
        *[
            f"domain-{index} | xn--example-{index} | Example language | Latin"
            for index in range(8)
        ],
        target_row,
        "final-domain | xn--final | Another language | Latin",
    ]
    text = (
        "# IANA-managed Reserved Domains\n"
        "The following table lists test domains.\n"
        + "\n".join(rows)
        + "\n## Policy-reserved domains\n"
        "These entries are not available for registration."
    )
    budget = 100

    assert count_tokens(text) > budget
    assert all(count_tokens(row) <= budget for row in rows)

    chunks = split_into_chunks(text, budget)

    assert len(chunks) > 1
    output_lines = [
        line.strip()
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    table_lines = [line for line in output_lines if "|" in line]

    _assert_table_chunks_preserve_content(
        chunks,
        [line.strip() for line in text.splitlines() if line.strip()],
        rows[0],
        rows[1],
    )
    assert sum(chunk.count(target_row) for chunk in chunks) == 1
    assert all(count_tokens(chunk) <= budget for chunk in chunks)

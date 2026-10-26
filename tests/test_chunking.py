from bintu_api.scraper import extract_text_result


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
    assert output_lines == expected_lines
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

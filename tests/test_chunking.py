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
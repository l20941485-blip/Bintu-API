from __future__ import annotations

from bintu_api.context_chunking import split_into_chunks
from bintu_api.scraper import extract_text_result


def _tokens(text: str) -> int:
    return -(-len(text) // 4)


def test_oversized_table_row_respects_budget_and_repeats_header():
    row = " | ".join(
        f"[Country {index}](https://example.com/country-{index})"
        for index in range(250)
    )
    html = f"""
    <html><body>
      <table>
        <tr><th>Country</th></tr>
        <tr><td>{row}</td></tr>
      </table>
    </body></html>
    """.encode()

    extracted = extract_text_result(html, 200000)
    chunks = split_into_chunks(extracted.text, 500)

    assert len(chunks) > 1

    for index, chunk in enumerate(chunks):
        assert _tokens(chunk) <= 500, (
            f"Chunk {index} has {_tokens(chunk)} tokens; budget is 500"
        )

    data_chunks = chunks[1:]
    assert data_chunks

    for index, chunk in enumerate(data_chunks, start=1):
        assert "Country" in chunk and "---" in chunk, (
            f"Data chunk {index} must repeat the table header"
        )

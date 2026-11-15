from bintu_api.extraction.context import count_tokens, split_into_chunks


def test_table_chunk_retains_active_section_heading():
    """A table that begins a later chunk must retain its section heading."""
    heading = "# Test IDN top-level domains"
    intro = (
        "These domains were temporarily delegated for the IDN Evaluation. "
        "They illustrate internationalized domain names across scripts."
    )
    table = (
        "| Domain | Domain (A-label) | Language | Script |\n"
        "| --- | --- | --- | --- |\n"
        "| العربية | xn--kgbechtv | Arabic | Arabic |\n"
        "| فارسی | xn--hgbk6aj7f53bba | Persian | Arabic |\n"
        "| 中文 | xn--0zwm56d | Chinese | Han Simplified |\n"
        "| Ελληνικά | xn--jxalpdlp | Greek, Modern | Greek |\n"
        "| 한국어 | xn--3e0bs7f | Korean | Hangul |\n"
        "| עברית | xn--4dbrk0ce | Hebrew | Hebrew |\n"
        "| 日本語 | xn--wgv71a | Japanese | Katakana |"
    )
    text = f"{heading}\n\n{intro}\n\n{table}\n"

    # Choose a budget that keeps the heading and prose together, then starts
    # a new chunk at the table.
    budget = count_tokens(f"{heading}\n\n{intro}\n\n") + 90
    chunks = split_into_chunks(text, budget)

    assert len(chunks) > 1
    table_chunk = next(
        chunk for chunk in chunks if "| Domain | Domain (A-label)" in chunk
    )
    assert heading in table_chunk

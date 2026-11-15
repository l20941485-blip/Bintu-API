from bintu_api.extraction.chunker import apply_link_policy


def test_links_false_removes_markdown_link_destination():
    text = (
        "Read the [documentation](https://example.com/docs).\n\n"
        "Visit [reference](https://example.com/reference) for details."
    )

    transformed = apply_link_policy(
        text,
        links="false",
        base_url="https://example.com/",
    )

    assert transformed == (
        "Read the documentation.\n\n"
        "Visit reference for details."
    )
    assert "https://example.com/docs" not in transformed
    assert "https://example.com/reference" not in transformed

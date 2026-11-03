from bintu_api import routes
from bintu_api.scraper import extract_text_result


def test_link_modes_are_defined():
    assert routes.LINK_MODES == ("inline", "footnotes", "false")


def test_invalid_link_mode_is_rejected():
    try:
        extract_text_result(
            b"<p>text</p>",
            max_characters=100,
            base_url="https://example.com/",
            links="bogus",
        )
    except ValueError as error:
        assert "links must be one of" in str(error)
    else:
        raise AssertionError("Expected ValueError for invalid links mode")


def test_inline_links_are_separated():
    result = extract_text_result(
        b"<p><a href='/a'>culture</a><a href='/b'>salt</a></p>",
        max_characters=1000,
        base_url="https://example.com/",
    )
    assert ")salt" not in result.text

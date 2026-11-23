from bintu_api.common.resolution import classify_content_type


def test_html_content_type_is_classified():
    assert classify_content_type("text/html; charset=utf-8") == "html"


def test_xhtml_content_type_is_classified_as_html():
    assert classify_content_type("application/xhtml+xml") == "html"


def test_pdf_content_type_is_classified():
    assert classify_content_type("application/pdf") == "pdf"


def test_json_content_type_is_classified():
    assert classify_content_type("application/json") == "json"


def test_text_json_content_type_is_classified():
    assert classify_content_type("text/json") == "json"


def test_plain_text_content_type_is_classified():
    assert classify_content_type("text/plain; charset=utf-8") == "text"


def test_image_content_type_is_classified():
    assert classify_content_type("image/png") == "image"


def test_missing_content_type_is_unsupported():
    assert classify_content_type(None) == "unsupported"


def test_empty_content_type_is_unsupported():
    assert classify_content_type("") == "unsupported"


def test_unknown_content_type_is_unsupported():
    assert classify_content_type("application/octet-stream") == "unsupported"

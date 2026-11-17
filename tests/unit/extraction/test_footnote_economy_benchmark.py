import math

from bintu_api.common.fetch import (
    compute_approx_tokens,
    compute_tokens_saved_estimate,
)
from bintu_api.extraction.html_extract import extract_text_result


LONG_URL = "https://example.com/very/long/documentation/path/with/many/segments"

HTML = f"""<!doctype html>
<html lang="en">
<head><title>Footnote economy benchmark</title></head>
<body>
<main>
<h1>Footnote economy benchmark</h1>
<p>
Read <a href="{LONG_URL}">the documentation</a> for details.
This page includes enough ordinary prose to make the extraction meaningful.
</p>
</main>
</body>
</html>
""".encode("utf-8")


def extract(links: str, policy: str = "truncated", limit: int = 20):
    return extract_text_result(
        HTML,
        max_characters=50000,
        include_nav=False,
        include_header=False,
        include_footer=False,
        from_encoding="utf-8",
        base_url="https://example.com/",
        links=links,
        footnote_url_policy=policy,
        max_footnote_url_length=limit,
    )


def measure(result):
    approx_tokens = compute_approx_tokens(result.text)
    return {
        "approx_tokens": approx_tokens,
        "html_tokens": compute_approx_tokens(HTML.decode("utf-8")),
        "tokens_saved_estimate": compute_tokens_saved_estimate(
            HTML,
            result.text,
        ),
    }


def test_footnote_economy_benchmark():
    inline = extract("inline")
    footnotes_full = extract("footnotes", policy="full", limit=20)
    footnotes_truncated = extract("footnotes", policy="truncated", limit=20)
    no_links = extract("false")

    results = {
        "inline": inline,
        "footnotes_full": footnotes_full,
        "footnotes_truncated": footnotes_truncated,
        "false": no_links,
    }

    measured = {
        name: measure(result)
        for name, result in results.items()
    }

    # The same source HTML produces one stable HTML token baseline.
    html_tokens = compute_approx_tokens(HTML.decode("utf-8"))
    assert len({item["html_tokens"] for item in measured.values()}) == 1
    assert html_tokens > 0

    # The link label remains available in every link mode.
    for result in results.values():
        assert "the documentation" in result.text

    # Inline retains the complete destination URL.
    assert LONG_URL in inline.text

    # Full footnotes move the URL into the Links section.
    assert "the documentation [1]" in footnotes_full.text
    assert "## Links" in footnotes_full.text
    assert LONG_URL in footnotes_full.text

    # Truncated footnotes replace the long URL, reducing output tokens.
    assert "the documentation [1]" in footnotes_truncated.text
    assert LONG_URL not in footnotes_truncated.text
    assert "[URL truncated]" in footnotes_truncated.text
    assert (
        measured["footnotes_truncated"]["approx_tokens"]
        < measured["footnotes_full"]["approx_tokens"]
    )

    # No-links mode removes the URL while preserving the label.
    assert "the documentation" in no_links.text
    assert LONG_URL not in no_links.text

    # Economy metrics remain internally consistent.
    for item in measured.values():
        assert item["tokens_saved_estimate"] >= 0
        assert item["tokens_saved_estimate"] == max(
            0,
            item["html_tokens"] - item["approx_tokens"],
        )

    # Record measured economy without assuming an ordering between inline
    # and footnote modes; footnote references and the Links section add output.
    assert measured["inline"]["approx_tokens"] > 0
    assert measured["footnotes_full"]["approx_tokens"] > 0
    assert measured["footnotes_truncated"]["approx_tokens"] > 0
    assert measured["false"]["approx_tokens"] > 0

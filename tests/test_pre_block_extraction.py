from bintu_api.scraper import extract_text_result


HTML = b"""
<html><body><article>
<h2>Standard Compliance</h2>
<p>Before code.</p>
<pre><code class=\"highlight-python3\">def custom_json(obj):
    if isinstance(obj, complex):
        return {'real': obj.real}</code></pre>
<p>After code. <a href=\"https://example.com/docs\">Docs</a></p>
</article></body></html>
"""


def test_pre_block_preserves_whitespace_and_avoids_link_annotation():
    result = extract_text_result(
        HTML,
        max_characters=20_000,
        base_url="https://example.com/docs/",
    )

    assert "def custom_json(obj):" in result.text
    assert "\n    if isinstance(obj, complex):" in result.text
    assert "```python3" in result.text
    assert result.text.count("```") % 2 == 0

    code_start = result.text.index("```python3")
    code_end = result.text.index("```", code_start + 3)
    assert "(https://" not in result.text[code_start:code_end]
    assert "Docs (https://example.com/docs)" in result.text


def test_truncation_closes_open_fence():
    result = extract_text_result(
        HTML,
        max_characters=120,
        base_url="https://example.com/docs/",
    )

    assert result.truncated is True
    assert len(result.text) <= 120
    assert result.text.count("```") % 2 == 0

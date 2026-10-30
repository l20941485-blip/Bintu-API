from bintu_api import mcp_descriptions as d
from bintu_api.yield_check import (
    HINT_JAVASCRIPT,
    HINT_LITTLE_TEXT,
    LOW_YIELD_MAX_TEXT_TOKENS,
    assess_yield,
)

# ---- low_yield --------------------------------------------------------------

QUOTES_JS = """<html><head><title>Quotes to Scrape</title><script src="/static/bootstrap.min.js"></script></head>
<body><div class="container"><h1><a href="/">Quotes to Scrape</a></h1><a href="/login">Login</a>
<div id="quotes"></div></div>
<script>
    var data = [ {"text": "The world as we have created it...", "author": {"name": "Albert Einstein"}} ];
    for (var i in data) { /* renders the quotes into #quotes */ }
</script></body></html>""" + (" " * 4400)  # pad to the ~1,450-token size seen live

REACT_SHELL = '<html><head><title>App</title></head><body><div id="root"></div><script src="/bundle.js"></script></body></html>' + (" " * 4400)
LOGIN_WALL = "<html><body><h1>Sign in</h1><form>" + "<input name='x'>" * 300 + "</form></body></html>"


def test_live_js_page_is_flagged_with_the_javascript_reason():
    result = assess_yield(23, 1452, QUOTES_JS)
    assert result.low_yield and result.reason == "javascript_rendered" and result.hint == HINT_JAVASCRIPT


def test_react_shell_is_flagged():
    assert assess_yield(12, 1400, REACT_SHELL).reason == "javascript_rendered"


def test_login_wall_is_flagged_as_little_text():
    result = assess_yield(8, 1600, LOGIN_WALL)
    assert result.low_yield and result.reason == "little_text" and result.hint == HINT_LITTLE_TEXT


def test_cache_hit_without_html_still_flags_by_numbers():
    result = assess_yield(23, 1452, "")  # persistent hit: html text is not stored
    assert result.low_yield and result.reason == "little_text"


def test_real_pages_measured_live_are_not_flagged():
    for extracted, html in [
        (1582, 93_200),  # BBC Africa
        (554, 2_737),  # IANA
        (8_261, 28_991),  # Python json docs
        (458, 8_850),  # MkDocs
        (44, 145),  # example.com: tiny page, nothing missing
        (268, 25_116),  # Hacker News thread
        (1_500, 247_000),  # Al Jazeera
    ]:
        assert not assess_yield(extracted, html).low_yield, (extracted, html)


def test_thresholds_are_respected_at_the_edges():
    assert assess_yield(LOW_YIELD_MAX_TEXT_TOKENS, 5000).low_yield
    assert not assess_yield(LOW_YIELD_MAX_TEXT_TOKENS + 1, 5000).low_yield
    assert not assess_yield(0, 999).low_yield  # a small page is never "low yield"
    assert not assess_yield(0, 0).low_yield


def test_ratio_must_also_be_low():
    assert not assess_yield(90, 1200).low_yield  # 7.5%: short but plausible, e.g. a landing page


def test_non_flagged_result_has_no_hint():
    result = assess_yield(500, 10_000)
    assert (result.low_yield, result.reason, result.hint) == (False, None, None)


# ---- tool description -------------------------------------------------------

STALE_PHRASES = [
    "6,000 characters",
    "ignored in scrape mode",
    "max_tokens is ignored",
    "sentence-based truncation",
    "Whitespace can be normalized",
]
ALL_TEXTS = [
    d.TOOL_DESCRIPTION, d.URL_DESCRIPTION, d.MODE_DESCRIPTION, d.MAX_TOKENS_DESCRIPTION,
    d.CACHE_DESCRIPTION, d.PERSIST_DESCRIPTION, d.RENDER_JS_DESCRIPTION,
]


def test_no_stale_claims_remain():
    for text in ALL_TEXTS:
        for phrase in STALE_PHRASES:
            assert phrase.lower() not in text.lower(), (phrase, text[:60])


def test_description_covers_the_verified_behaviour():
    text = d.TOOL_DESCRIPTION.lower()
    for needle in [
        "scrape", "chunk", "summarize", "max_tokens", "200,000 characters", "char_cap", "token_budget",
        "estimates", "tokens_saved_estimate", "low_yield", "cache=false", "persist=false",
        "credential-like query parameters", "robots.txt", "render_js", "iserror=true",
        "invalid_or_unsafe_url", "deduplicated_count", "fenced", "not an ai-written summary",
    ]:
        assert needle in text, needle


def test_max_tokens_text_matches_the_schema_range():
    assert "100 to 50000" in d.MAX_TOKENS_DESCRIPTION and "every mode" in d.MAX_TOKENS_DESCRIPTION
    assert "chunk_token_budget" in d.MAX_TOKENS_DESCRIPTION


def test_description_is_a_reasonable_length_for_an_agent_prompt():
    assert 800 < len(d.TOOL_DESCRIPTION) < 3000
    for text in ALL_TEXTS[1:]:
        assert len(text) < 500


def test_output_schema_additions_are_optional_and_typed():
    props = d.OUTPUT_SCHEMA_EXTRA_PROPERTIES
    assert props["low_yield"]["type"] == "boolean"
    assert props["yield_hint"]["type"] == "string"
    assert props["deduplicated_count"]["type"] == "integer"

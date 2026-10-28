import pytest

from bintu_api.extraction_quality import (
    dedupe_blocks,
    estimate_tokens,
    normalize_markdown,
    normalize_url,
    split_sentences,
    strip_noise_lines,
    truncate_to_token_budget,
)


LONG_TEXT = "\n".join(
    f"## Story {i}\nThis is the blurb for story number {i}, long enough to matter.\n"
    f"(https://news.example.com/articles/{i})"
    for i in range(300)
)


# ---- token budget ---------------------------------------------------------


@pytest.mark.parametrize("budget", [1, 100, 250, 500, 700, 2000])
def test_budget_is_never_exceeded(budget):
    out, truncated = truncate_to_token_budget(LONG_TEXT, budget)
    assert estimate_tokens(out) <= budget
    assert truncated is True


def test_budget_not_truncated_when_it_fits():
    out, truncated = truncate_to_token_budget("short text", 100)
    assert out == "short text"
    assert truncated is False


def test_no_budget_means_no_change():
    assert truncate_to_token_budget(LONG_TEXT, None) == (LONG_TEXT, False)


def test_zero_budget_returns_empty():
    assert truncate_to_token_budget("anything", 0) == ("", True)


def test_truncation_does_not_leave_half_url():
    text = (
        "Intro line\n"
        + "word " * 20
        + "(https://example.com/a/very/long/path/that/gets/cut)"
    )
    out, _ = truncate_to_token_budget(text, 30)

    assert not out.endswith("(https://example.com/a/very")
    assert "(http" not in out.split("\n")[-1] or out.rstrip().endswith("")


def test_truncation_is_deterministic():
    assert truncate_to_token_budget(LONG_TEXT, 500) == truncate_to_token_budget(
        LONG_TEXT, 500
    )


# ---- deduplication --------------------------------------------------------


ALJAZEERA_STYLE = """# Al Jazeera
## Iran searches for a way out
(https://www.aljazeera.net/news/liveblog/2026/10/28/iran-live)
Trump did not rule out more strikes.
## Iran searches for a way out
(https://www.aljazeera.net/news/liveblog/2026/10/28/iran-live)
Trump did not rule out more strikes.
## Sharaa receives al-Zaidi in Damascus
(https://www.aljazeera.net/news/2026/10/28/sharaa-zaidi)
## Sharaa receives al-Zaidi in Damascus
(https://www.aljazeera.net/news/2026/10/28/sharaa-zaidi?utm_source=home)
"""


def test_exact_and_tracking_param_duplicates_are_removed():
    out, removed = dedupe_blocks(ALJAZEERA_STYLE)

    assert removed == 2
    assert out.count("Iran searches for a way out") == 1
    assert out.count("Sharaa receives") == 1


def test_same_heading_different_urls_are_kept():
    text = "## Related\n(https://a.com/1)\n## Related\n(https://a.com/2)"
    out, removed = dedupe_blocks(text)

    assert removed == 0
    assert out == text


def test_repeated_docs_heading_with_different_body_is_kept():
    text = "## Example\nFirst body.\n## Example\nSecond body."
    _, removed = dedupe_blocks(text)

    assert removed == 0


def test_bbc_latest_updates_repeat_is_removed():
    text = (
        "## Tanzania celebrates gas discovery\n"
        "Minister called it a milestone.\n"
        "3 hrs ago\n"
        "(https://www.bbc.com/news/articles/c5m2dry2xwwvo)\n"
        "## Latest updates\n"
        "## Tanzania celebrates gas discovery\n"
        "(https://www.bbc.com/news/articles/c5m2dry2xwwvo/)\n"
    )
    out, removed = dedupe_blocks(text)

    assert removed == 1
    assert out.count("Tanzania celebrates") == 1


def test_preamble_before_first_heading_is_kept():
    out, removed = dedupe_blocks("intro line\n## A\n(https://x.com/a)")

    assert removed == 0
    assert out.startswith("intro line")


def test_normalize_url_strips_tracking_and_fragment():
    assert (
        normalize_url("https://X.com/a/?utm_source=t&id=2#top")
        == "https://x.com/a?id=2"
    )


# ---- markdown normalization ----------------------------------------------


def test_glued_heading_moves_to_its_own_line():
    out = normalize_markdown(
        "kept for documentation purposes. ## Example domains\nBody."
    )

    assert "purposes.\n## Example domains" in out


def test_c_sharp_and_issue_numbers_are_untouched():
    text = "We use C# language and fix issue #12 today."

    assert normalize_markdown(text) == text


# ---- noise ----------------------------------------------------------------


def test_noise_lines_are_dropped():
    text = (
        "Headline\n"
        "list 1 of 10\n"
        "This video may contain flashing images\n"
        "أخبار\n"
        "قد يحتوي هذا الفيديو أنماطا ضوئية\n"
        "Body"
    )
    out = strip_noise_lines(text)

    assert out.split("\n") == ["Headline", "أخبار", "Body"]


# ---- sentence splitting ---------------------------------------------------


def test_domains_are_not_split():
    text = (
        "Domains such as example.com and example.org are reserved. "
        "They are not for sale."
    )
    sentences = split_sentences(text)

    assert sentences[0].endswith("reserved.")
    assert "example.org" in sentences[0]
    assert len(sentences) == 2


def test_urls_and_abbreviations_survive():
    text = (
        "Dr. Smith visited the U.S. office. "
        "See [https://www.bbc.co.uk/news](https://www.bbc.co.uk/news) for more."
    )
    sentences = split_sentences(text)

    assert len(sentences) == 2
    assert "https://www.bbc.co.uk/news" in sentences[1]

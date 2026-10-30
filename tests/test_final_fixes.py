from bintu_api.final_fixes import (
    close_up_punctuation,
    delivered_savings,
    drop_empty_fences,
    has_credential_params,
)


def test_credential_detection():
    assert has_credential_params("https://x.org/a?Token=1")
    assert has_credential_params("https://x.org/a?x=1&API_KEY=z")
    assert has_credential_params("https://x.org/a?session=")
    assert not has_credential_params("https://x.org/a?q=a%20b&page=2")
    assert not has_credential_params("https://x.org/a?monkey=1")
    assert not has_credential_params("https://x.org/a")


def test_savings_follow_the_delivered_text():
    assert delivered_savings(83_642, 2_564) == 81_078
    assert delivered_savings(83_642, 265) == 83_377
    assert delivered_savings(100, 500) == 0


def test_leading_dot_names_keep_their_space():
    source = "Files with names which begin with a dot (for example: .foo.md or .bar/baz.md) are ignored."
    assert close_up_punctuation(source) == source
    assert close_up_punctuation("a .write()-supporting file and A .read()-supporting one") == (
        "a .write()-supporting file and A .read()-supporting one"
    )
    assert close_up_punctuation("edit the .env file") == "edit the .env file"


def test_space_before_sentence_punctuation_is_closed_up():
    assert close_up_punctuation("Hello , world .") == "Hello, world."
    assert close_up_punctuation("Really ?") == "Really?"
    assert close_up_punctuation("see the list : one ; two") == "see the list: one; two"
    assert close_up_punctuation("JavaScript [1] ).") == "JavaScript [1])."
    assert close_up_punctuation("(see this )") == "(see this)"
    assert close_up_punctuation("end .") == "end."


def test_old_regex_had_the_bug():
    import re

    old = lambda value: re.sub(r"\s+([,.;:!?])", r"\1", value)
    assert old("for example: .foo.md or .bar/baz.md") == "for example:.foo.md or.bar/baz.md"
    assert close_up_punctuation("for example: .foo.md or .bar/baz.md") == (
        "for example: .foo.md or .bar/baz.md"
    )


def test_decimal_urls_and_paths_are_untouched():
    for text in (
        "version 3.15.2 of json.org",
        "see [https://x.org/a.b](https://x.org/a.b) and src/app.py",
        "pi is 3 .14",
    ):
        assert close_up_punctuation(text) == text


def test_trailing_empty_fence_is_removed():
    text = "And providing you are in foo/one.md:\nmd\n```md\n```"
    assert drop_empty_fences(text) == "And providing you are in foo/one.md:\nmd"


def test_adjacent_non_empty_fences_are_untouched():
    text = "```python\nx = 1\n```\n```shell\n$ run\n```"
    assert drop_empty_fences(text) == text


def test_empty_fence_between_blocks_is_removed_only():
    text = "intro\n```\n```\nmiddle\n```python\nprint(1)\n```\nend"
    assert drop_empty_fences(text) == "intro\nmiddle\n```python\nprint(1)\n```\nend"


def test_whitespace_only_body_is_kept_as_is():
    text = "```\n \n```"
    assert drop_empty_fences(text) == text


def test_text_without_fences_is_unchanged():
    assert drop_empty_fences("plain\ntext") == "plain\ntext"

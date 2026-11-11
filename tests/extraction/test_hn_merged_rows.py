"""Regression coverage for nested Hacker News story and metadata rows."""

from pathlib import Path

from bintu_api.extraction.html_extract import extract_text_result

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "hn_merged_rows_synthetic.html"


def test_nested_hn_rows_preserve_comments_and_the_following_story():
    result = extract_text_result(
        FIXTURE.read_bytes(),
        max_characters=5000,
        base_url="https://news.ycombinator.com/",
        links="false",
    )
    lines = result.text.splitlines()
    normalized_text = " ".join(result.text.split())

    assert "848 comments 2." in normalized_text
    assert sum("848 comments" in line for line in lines) == 1

    metadata_row = next(index for index, line in enumerate(lines) if "848 comments" in line)
    next_story_row = next(
        index for index, line in enumerate(lines) if "2. Second story title" in line
    )
    next_metadata_row = next(
        index for index, line in enumerate(lines) if "24 points" in line
    )
    assert metadata_row < next_story_row
    assert metadata_row != next_story_row
    assert next_story_row < next_metadata_row




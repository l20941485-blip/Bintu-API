"""Extraction checks against a saved, point-in-time Hacker News page."""

from pathlib import Path

from bintu_api.scraper.fetcher import extract_text_result

FIXTURE = Path(__file__).parent / "fixtures" / "hn_frontpage_capture.html"


def test_saved_hn_capture_keeps_story_rows_and_metadata_separate():
    raw_html = FIXTURE.read_bytes()
    provenance = raw_html.splitlines()[0].decode("utf-8")
    assert "Point-in-time fixture" in provenance
    assert "https://news.ycombinator.com/" in provenance
    assert "Captured:" in provenance

    result = extract_text_result(
        raw_html,
        max_characters=50000,
        base_url="https://news.ycombinator.com/",
    )
    lines = result.text.splitlines()

    first_title = next(
        index
        for index, line in enumerate(lines)
        if "Jailbreaking my car's navigation system just so I can change the time" in line
    )
    first_metadata = next(
        index for index, line in enumerate(lines) if "111 points by xx_ns" in line
    )
    second_title = next(
        index for index, line in enumerate(lines) if "Fujifilm to boost tape production" in line
    )
    second_metadata = next(
        index for index, line in enumerate(lines) if "145 points by bookofjoe" in line
    )

    assert first_title < first_metadata < second_title < second_metadata
    assert first_title != first_metadata
    assert second_title != second_metadata




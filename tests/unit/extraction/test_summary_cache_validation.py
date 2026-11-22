from bintu_api.extraction.summary_cache import validate_cached_extractive_summary


MARKDOWN = """# Example

First useful sentence.

Second useful sentence.
"""


def build_summary_payload(markdown: str = MARKDOWN) -> dict:
    import hashlib

    sentence = "First useful sentence."
    start = markdown.index(sentence)

    return {
        "applied": True,
        "mode": "leading",
        "requested_sentence_count": 1,
        "returned_sentence_count": 1,
        "truncated": False,
        "algorithm_version": "v1-grounded-mmr",
        "source_fingerprint": hashlib.sha256(
            markdown.encode("utf-8")
        ).hexdigest(),
        "sentences": [
            {
                "text": sentence,
                "heading_path": ["Example"],
                "char_start": start,
                "char_end": start + len(sentence),
                "score": 1.0,
            }
        ],
    }


def test_missing_metadata_is_not_invalid():
    result = validate_cached_extractive_summary(MARKDOWN, None)

    assert result.status == "missing_metadata"
    assert result.summary_payload is None


def test_valid_cached_summary_passes_all_checks():
    payload = build_summary_payload()

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "valid"
    assert result.summary_payload == payload


def test_changed_cached_markdown_fails_fingerprint():
    payload = build_summary_payload()

    result = validate_cached_extractive_summary(
        MARKDOWN + "\nChanged content.\n",
        payload,
    )

    assert result.status == "source_changed"
    assert result.summary_payload is None


def test_old_algorithm_version_fails():
    payload = build_summary_payload()
    payload["algorithm_version"] = "v0-legacy"

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "stale_algorithm"
    assert result.summary_payload is None


def test_sentence_outside_source_bounds_fails_grounding():
    payload = build_summary_payload()
    payload["sentences"][0]["char_end"] = len(MARKDOWN) + 10

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "ungrounded"
    assert result.summary_payload is None


def test_modified_sentence_text_fails_exact_grounding():
    payload = build_summary_payload()
    payload["sentences"][0]["text"] = "Altered sentence."

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "ungrounded"
    assert result.summary_payload is None


def test_non_dict_payload_is_rejected_safely():
    result = validate_cached_extractive_summary(MARKDOWN, "not-a-dict")

    assert result.status == "malformed"
    assert result.summary_payload is None


def test_missing_required_fields_is_rejected_safely():
    payload = build_summary_payload()
    del payload["source_fingerprint"]

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "malformed"
    assert result.summary_payload is None


def test_invalid_sentence_type_is_rejected_safely():
    payload = build_summary_payload()
    payload["sentences"] = ["not-a-dict"]

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "malformed"
    assert result.summary_payload is None



def test_invalid_position_type_is_rejected_safely():
    payload = build_summary_payload()
    payload["sentences"][0]["char_start"] = "0"

    result = validate_cached_extractive_summary(MARKDOWN, payload)

    assert result.status == "malformed"
    assert result.summary_payload is None

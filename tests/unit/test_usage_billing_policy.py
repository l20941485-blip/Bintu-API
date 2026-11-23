"""Billing-policy classification for usage events."""


from bintu_api.metering.billing import classify_usage


def test_fresh_context_uses_context_tokens_without_cache_credit():
    decision = classify_usage(
        tokens=4735,
        mode="scrape",
        cache_hit=False,
    )

    assert decision.billable_units == 4735
    assert decision.unit == "context_tokens"
    assert decision.cache_credit_applied is False


def test_cached_context_applies_cache_credit():
    decision = classify_usage(
        tokens=4735,
        mode="scrape",
        cache_hit=True,
    )

    assert decision.billable_units == 4735
    assert decision.unit == "context_tokens"
    assert decision.cache_credit_applied is True


def test_chunk_retrieval_uses_chunk_tokens():
    decision = classify_usage(
        tokens=312,
        mode="chunk",
        cache_hit=False,
    )

    assert decision.billable_units == 312
    assert decision.unit == "chunk_tokens"
    assert decision.cache_credit_applied is False


def test_cached_chunk_retrieval_applies_cache_credit():
    decision = classify_usage(
        tokens=312,
        mode="chunk",
        cache_hit=True,
    )

    assert decision.billable_units == 312
    assert decision.unit == "chunk_tokens"
    assert decision.cache_credit_applied is True


def test_failed_extraction_bills_nothing():
    decision = classify_usage(
        tokens=4735,
        mode="scrape",
        cache_hit=False,
        extraction_failed=True,
    )

    assert decision.billable_units == 0
    assert decision.unit == "context_tokens"
    assert decision.cache_credit_applied is False


def test_quality_rejected_result_bills_nothing():
    decision = classify_usage(
        tokens=4735,
        mode="scrape",
        cache_hit=False,
        quality_rejected=True,
    )

    assert decision.billable_units == 0
    assert decision.unit == "context_tokens"
    assert decision.cache_credit_applied is False


def test_negative_tokens_are_clamped_to_zero():
    decision = classify_usage(
        tokens=-10,
        mode="scrape",
        cache_hit=False,
    )

    assert decision.billable_units == 0
    assert decision.unit == "context_tokens"
    assert decision.cache_credit_applied is False

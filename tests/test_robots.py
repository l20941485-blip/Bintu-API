from types import SimpleNamespace

import pytest

from bintu_api import robots
from bintu_api.robots import (
    RobotsUnreachable,
    clear_robots_cache,
    parse_robots_rules,
    robots_decision,
    robots_target,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_robots_cache()
    yield
    clear_robots_cache()


def settings(**overrides):
    base = {
        "robots_mode": "enforce",
        "robots_cache_ttl_seconds": 3600,
        "allowed_ports": [80, 443],
        "blocked_hosts": [],
        "user_agent": "BintuBot/1.0",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_robots_target_includes_query():
    assert robots_target("https://example.com/a?b=1") == "/a?b=1"
    assert robots_target("https://example.com") == "/"


def test_parse_prefers_own_group():
    rules = parse_robots_rules(
        """
        User-agent: *
        Disallow: /private/

        User-agent: bintubot
        Allow: /private/ok
        Disallow: /private/
        """
    )

    assert rules.matched_group == "own"
    assert rules.is_allowed("/private/ok") is True
    assert rules.is_allowed("/private/secret") is False


def test_parse_wildcard_group():
    rules = parse_robots_rules(
        """
        User-agent: *
        Disallow: /admin
        """
    )

    assert rules.matched_group == "*"
    assert rules.is_allowed("/admin") is False
    assert rules.is_allowed("/public") is True


def test_explicit_disallow_returns_descriptive_reason(monkeypatch):
    def fake_fetch(origin, settings):
        return "User-agent: *\nDisallow: /private/\n"

    monkeypatch.setattr(robots, "_fetch_robots_text", fake_fetch)

    decision = robots_decision(
        "https://example.com/private/page",
        settings(),
    )

    assert decision.allowed is False
    assert decision.reason == "disallowed by robots.txt (group: *)"
    assert decision.unreachable is False
    assert decision.checked is True
    assert decision.matched_group == "*"


def test_unreachable_robots_preserves_failure_reason(monkeypatch):
    def fake_fetch(origin, settings):
        raise RobotsUnreachable("HTTP 503")

    monkeypatch.setattr(robots, "_fetch_robots_text", fake_fetch)

    decision = robots_decision("https://example.com/page", settings())

    assert decision.allowed is False
    assert decision.reason == "robots.txt could not be retrieved (HTTP 503)"
    assert decision.unreachable is True
    assert decision.checked is True


def test_missing_robots_allows_fetch(monkeypatch):
    def fake_fetch(origin, settings):
        return None

    monkeypatch.setattr(robots, "_fetch_robots_text", fake_fetch)

    decision = robots_decision("https://example.com/page", settings())

    assert decision.allowed is True
    assert decision.reason == "allowed by robots.txt (group: none)"
    assert decision.unreachable is False
    assert decision.matched_group == "none"


def test_unreachable_result_is_cached(monkeypatch):
    calls = []

    def fake_fetch(origin, settings):
        calls.append(origin)
        raise RobotsUnreachable("connection problem")

    monkeypatch.setattr(robots, "_fetch_robots_text", fake_fetch)

    first = robots_decision("https://example.com/page", settings())
    second = robots_decision("https://example.com/other", settings())

    expected_reason = "robots.txt could not be retrieved (connection problem)"

    assert first.allowed is False
    assert second.allowed is False
    assert first.unreachable is True
    assert second.unreachable is True
    assert first.reason == expected_reason
    assert second.reason == expected_reason
    assert calls == ["https://example.com"]


def test_disallow_root_blocks_page(monkeypatch):
    def fake_fetch(origin, settings):
        return "User-agent: *\nDisallow: /\n"

    monkeypatch.setattr(robots, "_fetch_robots_text", fake_fetch)

    decision = robots_decision("https://example.com/page", settings())

    assert decision.allowed is False
    assert decision.reason == "disallowed by robots.txt (group: *)"
    assert decision.unreachable is False


def test_robots_off_allows_without_check(monkeypatch):
    def fail_fetch(origin, settings):
        raise AssertionError("robots fetch should not run")

    monkeypatch.setattr(robots, "_fetch_robots_text", fail_fetch)

    decision = robots_decision(
        "https://example.com/page",
        settings(robots_mode="off"),
    )

    assert decision.allowed is True
    assert decision.checked is False
    assert decision.reason == "robots checking is off"
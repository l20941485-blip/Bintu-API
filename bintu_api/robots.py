"""robots.txt support for BintuBot.

Parsing, safe fetching, per-origin caching and allow/deny decisions live
here. Fetching uses public-address validation and pinned connections.

A shared elapsed-time budget covers all redirect hops. Budget checks run
around blocking stages, and socket timeouts use the remaining budget.
This is not a hard execution deadline: synchronous DNS and individual
blocking HTTP operations may finish after the budget has expired.
"""

from __future__ import annotations

import http.client
import socket
import threading
import time
import zlib
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from bintu_api.scraper import (
    REDIRECT_STATUSES,
    TargetURLRejected,
    _host_header,
    _make_connection,
    _parse_target,
    get_user_agent,
    resolve_public_addresses,
)
from bintu_api.settings import Settings


PRODUCT_TOKEN = "bintubot"
MAX_ROBOTS_BYTES = 512 * 1024
MAX_PATTERN_LENGTH = 1024
MAX_RULES = 5000
MAX_ROBOTS_REDIRECTS = 5
UNREACHABLE_TTL_SECONDS = 60
MAX_CACHE_ENTRIES = 512
VALID_MODES = ("enforce", "warn", "off")
ROBOTS_TIMEOUT_SECONDS = 8.0


class RobotsUnreachable(Exception):
    """robots.txt could not be retrieved."""


@dataclass(frozen=True)
class RobotsRules:
    rules: tuple
    matched_group: str

    def is_allowed(self, path_and_query: str) -> bool:
        target = path_and_query or "/"
        if target.split("?", 1)[0] == "/robots.txt":
            return True

        best_length = -1
        best_allow = True

        for allow, pattern in self.rules:
            if _rule_matches(pattern, target):
                length = len(pattern)
                if length > best_length or (
                    length == best_length and allow
                ):
                    best_length, best_allow = length, allow

        return best_allow


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str
    checked: bool = True
    matched_group: str = "none"
    unreachable: bool = False


def _glob_full_match(pattern: str, text: str) -> bool:
    p = t = 0
    star = -1
    mark = 0

    while t < len(text):
        if p < len(pattern) and pattern[p] == "*":
            star = p
            p += 1
            mark = t
        elif p < len(pattern) and pattern[p] == text[t]:
            p += 1
            t += 1
        elif star != -1:
            p = star + 1
            mark += 1
            t = mark
        else:
            return False

    while p < len(pattern) and pattern[p] == "*":
        p += 1

    return p == len(pattern)


def _rule_matches(pattern: str, target: str) -> bool:
    if len(pattern) > MAX_PATTERN_LENGTH:
        return False
    if pattern.endswith("$"):
        return _glob_full_match(pattern[:-1], target)
    return _glob_full_match(pattern + "*", target)


def parse_robots_rules(
    content: str,
    product_token: str = PRODUCT_TOKEN,
) -> RobotsRules:
    token = product_token.lower()
    groups: list = []
    agents: list = []
    rules: list = []
    in_rules = False

    for raw in content.lstrip("\ufeff").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue

        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            if in_rules:
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(value.lower())

        elif key in ("allow", "disallow"):
            if not agents:
                continue
            in_rules = True
            if value and value[0] in "/*" and len(rules) < MAX_RULES:
                rules.append((key == "allow", value))

    if agents:
        groups.append((agents, rules))

    own = [
        group_rules
        for group_agents, group_rules in groups
        if token in group_agents
    ]
    wildcard = [
        group_rules
        for group_agents, group_rules in groups
        if "*" in group_agents
    ]

    if own:
        chosen, label = own, "own"
    elif wildcard:
        chosen, label = wildcard, "*"
    else:
        chosen, label = [], "none"

    return RobotsRules(
        rules=tuple(
            rule
            for group_rules in chosen
            for rule in group_rules
        ),
        matched_group=label,
    )


def robots_target(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return path + (f"?{parts.query}" if parts.query else "")


def robots_mode(settings) -> str:
    mode = str(
        getattr(settings, "robots_mode", "enforce") or "enforce"
    ).strip().lower()
    return mode if mode in VALID_MODES else "enforce"


def _remaining_budget(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RobotsUnreachable(
            "robots.txt retrieval budget exhausted (TimeoutError)"
        )
    return remaining


def _apply_remaining_timeout(connection, deadline: float) -> float:
    """Update both future connection and currently connected socket timeouts."""
    remaining = _remaining_budget(deadline)
    connection.timeout = remaining

    connected_socket = getattr(connection, "sock", None)
    if connected_socket is not None:
        connected_socket.settimeout(remaining)

    return remaining


def _read_robots_body(response) -> str:
    encoding = (
        response.getheader("Content-Encoding") or "identity"
    ).strip().lower()
    raw = response.read(MAX_ROBOTS_BYTES + 1)

    if encoding in ("gzip", "x-gzip"):
        try:
            raw = zlib.decompressobj(
                16 + zlib.MAX_WBITS
            ).decompress(
                raw,
                MAX_ROBOTS_BYTES + 1,
            )
        except zlib.error as error:
            raise RobotsUnreachable("invalid gzip") from error
    elif encoding not in ("", "identity"):
        raise RobotsUnreachable("unsupported content encoding")

    return raw[:MAX_ROBOTS_BYTES].decode(
        "utf-8",
        errors="replace",
    )


def _fetch_robots_text(
    origin: str,
    settings: Settings,
) -> str | None:
    deadline = time.monotonic() + ROBOTS_TIMEOUT_SECONDS
    current = f"{origin}/robots.txt"
    current_scheme = urlsplit(current).scheme

    for hop in range(MAX_ROBOTS_REDIRECTS + 1):
        _remaining_budget(deadline)

        try:
            parsed, host, port, path = _parse_target(
                current,
                settings,
            )
            _remaining_budget(deadline)
            address = resolve_public_addresses(host, port)[0]
        except TargetURLRejected as error:
            if hop == 0:
                raise
            raise RobotsUnreachable(
                "a redirect led to a disallowed target"
            ) from error

        remaining = _remaining_budget(deadline)

        if current_scheme == "https" and parsed.scheme == "http":
            raise RobotsUnreachable("redirect from https to http")

        current_scheme = parsed.scheme
        connection = None

        try:
            connection = _make_connection(
                parsed,
                host,
                address,
                port,
                remaining,
            )

            _apply_remaining_timeout(connection, deadline)
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/plain, */*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "Host": _host_header(
                        host,
                        port,
                        parsed.scheme,
                    ),
                    "User-Agent": get_user_agent(settings),
                },
            )

            _apply_remaining_timeout(connection, deadline)
            response = connection.getresponse()
            _remaining_budget(deadline)
            status = response.status

            if status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    return None
                current = urljoin(current, location)
                _remaining_budget(deadline)
                continue

            if 400 <= status < 500:
                return None

            if not 200 <= status < 300:
                raise RobotsUnreachable(f"HTTP {status}")

            _apply_remaining_timeout(connection, deadline)
            text = _read_robots_body(response)
            _remaining_budget(deadline)
            return text

        except (
            OSError,
            http.client.HTTPException,
            socket.timeout,
            TimeoutError,
        ) as error:
            raise RobotsUnreachable(
                f"connection problem ({type(error).__name__})"
            ) from error
        finally:
            if connection is not None:
                connection.close()

    return None


_cache: dict = {}
_cache_lock = threading.Lock()


def clear_robots_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_ttl(settings) -> int:
    try:
        ttl = int(
            getattr(
                settings,
                "robots_cache_ttl_seconds",
                3600,
            )
        )
    except (TypeError, ValueError):
        ttl = 3600

    return max(0, min(ttl, 86400))


def _rules_for_origin(origin: str, settings: Settings):
    now = time.monotonic()

    with _cache_lock:
        entry = _cache.get(origin)

    if entry is not None and entry[0] > now:
        return entry[1], entry[2]

    try:
        text = _fetch_robots_text(origin, settings)
        rules = (
            parse_robots_rules(text)
            if text is not None
            else RobotsRules(rules=(), matched_group="none")
        )
        entry = (now + _cache_ttl(settings), rules, None)
    except RobotsUnreachable as error:
        entry = (
            now + UNREACHABLE_TTL_SECONDS,
            None,
            str(error),
        )

    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[origin] = entry

    return entry[1], entry[2]


def robots_decision(
    url: str,
    settings: Settings,
) -> RobotsDecision:
    """Distinguish explicit disallows from robots retrieval failures."""
    if robots_mode(settings) == "off":
        return RobotsDecision(
            allowed=True,
            reason="robots checking is off",
            checked=False,
        )

    parsed, host, port, _ = _parse_target(url, settings)
    origin = (
        f"{parsed.scheme}://"
        f"{_host_header(host, port, parsed.scheme)}"
    )
    rules, problem = _rules_for_origin(origin, settings)

    if rules is None:
        return RobotsDecision(
            allowed=False,
            reason=(
                "robots.txt could not be retrieved "
                f"({problem})"
            ),
            unreachable=True,
        )

    if rules.is_allowed(robots_target(url)):
        return RobotsDecision(
            allowed=True,
            reason=(
                "allowed by robots.txt "
                f"(group: {rules.matched_group})"
            ),
            matched_group=rules.matched_group,
        )

    return RobotsDecision(
        allowed=False,
        reason=(
            "disallowed by robots.txt "
            f"(group: {rules.matched_group})"
        ),
        matched_group=rules.matched_group,
    )
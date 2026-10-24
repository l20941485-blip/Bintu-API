"""robots.txt support for BintuBot (RFC 9309).

Parsing, safe fetching, per-origin caching and the allow/deny decision live here, so
scraper.py stays focused on SSRF-safe page fetching and text extraction. robots.txt
is fetched through the same guards as pages: public addresses only, connections
pinned to the validated address, allowed ports only, no https -> http downgrade.
"""

from __future__ import annotations

import http.client
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


class RobotsUnreachable(Exception):
    """robots.txt could not be retrieved (5xx, timeout, connection problem). RFC 9309: treat as disallow."""


@dataclass(frozen=True)
class RobotsRules:
    """The rules that apply to BintuBot, chosen per RFC 9309."""

    rules: tuple  # tuple of (allow: bool, pattern: str)
    matched_group: str  # "own", "*" or "none"

    def is_allowed(self, path_and_query: str) -> bool:
        target = path_and_query or "/"
        if target.split("?", 1)[0] == "/robots.txt":
            return True
        best_length = -1
        best_allow = True
        for allow, pattern in self.rules:
            if _rule_matches(pattern, target):
                length = len(pattern)
                if length > best_length or (length == best_length and allow):
                    best_length, best_allow = length, allow
        return best_allow


@dataclass(frozen=True)
class RobotsDecision:
    allowed: bool
    reason: str
    checked: bool = True
    matched_group: str = "none"


def _glob_full_match(pattern: str, text: str) -> bool:
    """Wildcard match where '*' matches any run of characters (linear-time backtracking)."""
    p = t = 0
    star = -1
    mark = 0
    while t < len(text):
        if p < len(pattern) and pattern[p] == "*":
            star = p
            mark = t
            p += 1
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


def parse_robots_rules(content: str, product_token: str = PRODUCT_TOKEN) -> RobotsRules:
    """Parse robots.txt text. Our own group wins over '*'; groups for the same agent are merged."""
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
            # An empty rule adds no restriction; patterns must start with '/' or '*'.
            if value and value[0] in "/*" and len(rules) < MAX_RULES:
                rules.append((key == "allow", value))
    if agents:
        groups.append((agents, rules))

    own = [group_rules for group_agents, group_rules in groups if token in group_agents]
    wildcard = [group_rules for group_agents, group_rules in groups if "*" in group_agents]
    if own:
        chosen, label = own, "own"
    elif wildcard:
        chosen, label = wildcard, "*"
    else:
        chosen, label = [], "none"
    return RobotsRules(
        rules=tuple(rule for group_rules in chosen for rule in group_rules),
        matched_group=label,
    )


def robots_target(url: str) -> str:
    """The path (plus query) that robots rules are matched against."""
    parts = urlsplit(url)
    path = parts.path or "/"
    return path + (f"?{parts.query}" if parts.query else "")


def robots_mode(settings) -> str:
    mode = str(getattr(settings, "robots_mode", "enforce") or "enforce").strip().lower()
    return mode if mode in VALID_MODES else "enforce"


def _read_robots_body(response) -> str:
    encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
    raw = response.read(MAX_ROBOTS_BYTES + 1)
    if encoding in ("gzip", "x-gzip"):
        try:
            raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, MAX_ROBOTS_BYTES + 1)
        except zlib.error as error:
            raise RobotsUnreachable("invalid gzip") from error
    elif encoding not in ("", "identity"):
        raise RobotsUnreachable("unsupported content encoding")
    return raw[:MAX_ROBOTS_BYTES].decode("utf-8", errors="replace")


def _fetch_robots_text(origin: str, settings: Settings) -> str | None:
    """Fetch /robots.txt for an origin through the same SSRF guards as page fetches.

    Returns the text, or None when the file does not exist (any 4xx, or a redirect
    chain that is too long). Raises RobotsUnreachable for 5xx, timeouts and
    connection problems. A rejected origin raises TargetURLRejected, exactly as the
    page fetch would.
    """
    current = f"{origin}/robots.txt"
    current_scheme = urlsplit(current).scheme
    for hop in range(MAX_ROBOTS_REDIRECTS + 1):
        try:
            parsed, host, port, path = _parse_target(current, settings)
            address = resolve_public_addresses(host, port)[0]
        except TargetURLRejected as error:
            if hop == 0:
                raise
            raise RobotsUnreachable("a redirect led to a disallowed target") from error
        if current_scheme == "https" and parsed.scheme == "http":
            raise RobotsUnreachable("redirect from https to http")
        current_scheme = parsed.scheme
        connection = _make_connection(parsed, host, address, port, settings.request_timeout_seconds)
        try:
            connection.request(
                "GET",
                path,
                headers={
                    "Accept": "text/plain, */*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                    "Host": _host_header(host, port, parsed.scheme),
                    "User-Agent": get_user_agent(settings),
                },
            )
            response = connection.getresponse()
            status = response.status
            if status in REDIRECT_STATUSES:
                location = response.getheader("Location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if 400 <= status < 500:
                return None
            if not 200 <= status < 300:
                raise RobotsUnreachable(f"HTTP {status}")
            return _read_robots_body(response)
        except (OSError, http.client.HTTPException) as error:
            raise RobotsUnreachable("connection problem") from error
        finally:
            connection.close()
    return None


_cache: dict = {}
_cache_lock = threading.Lock()


def clear_robots_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_ttl(settings) -> int:
    try:
        ttl = int(getattr(settings, "robots_cache_ttl_seconds", 3600))
    except (TypeError, ValueError):
        ttl = 3600
    return max(0, min(ttl, 86400))


def _rules_for_origin(origin: str, settings: Settings):
    """Return (rules, problem). rules is None when robots.txt was unreachable."""
    now = time.monotonic()
    with _cache_lock:
        entry = _cache.get(origin)
    if entry is not None and entry[0] > now:
        return entry[1], entry[2]
    try:
        text = _fetch_robots_text(origin, settings)
        rules = parse_robots_rules(text) if text is not None else RobotsRules(rules=(), matched_group="none")
        entry = (now + _cache_ttl(settings), rules, None)
    except RobotsUnreachable as error:
        entry = (now + UNREACHABLE_TTL_SECONDS, None, str(error))
    with _cache_lock:
        if len(_cache) >= MAX_CACHE_ENTRIES:
            _cache.clear()
        _cache[origin] = entry
    return entry[1], entry[2]


def robots_decision(url: str, settings: Settings) -> RobotsDecision:
    """Decide whether BintuBot may fetch this URL.

    Fail-closed: if robots.txt cannot be retrieved (5xx, timeout, connection problem) the
    answer is "not allowed". A URL the safety checks reject raises TargetURLRejected,
    so callers report it exactly as they report an unsafe page URL.
    """
    if robots_mode(settings) == "off":
        return RobotsDecision(allowed=True, reason="robots checking is off", checked=False)
    parsed, host, port, _ = _parse_target(url, settings)
    origin = f"{parsed.scheme}://{_host_header(host, port, parsed.scheme)}"
    rules, problem = _rules_for_origin(origin, settings)
    if rules is None:
        return RobotsDecision(
            allowed=False,
            reason=f"robots.txt could not be retrieved ({problem})",
        )
    if rules.is_allowed(robots_target(url)):
        return RobotsDecision(
            allowed=True,
            reason=f"allowed by robots.txt (group: {rules.matched_group})",
            matched_group=rules.matched_group,
        )
    return RobotsDecision(
        allowed=False,
        reason=f"disallowed by robots.txt (group: {rules.matched_group})",
        matched_group=rules.matched_group,
    )

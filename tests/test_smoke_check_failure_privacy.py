"""Response bodies must not appear in smoke-check failure output."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import smoke_check


SENSITIVE = "PRIVATE_RESPONSE_BODY_DO_NOT_LOG"


def response(status, payload):
    return status, {}, json.dumps(payload).encode("utf-8")


def successful_prefix():
    return [
        response(200, {"status": "ok"}),
        (
            200,
            {"X-Request-ID": "offline-request"},
            json.dumps({"text": "Example text"}).encode("utf-8"),
        ),
    ]


class SmokeCheckFailurePrivacyTests(unittest.TestCase):
    def assert_private_failure(self, responses, expected_message):
        stdout = io.StringIO()
        stderr = io.StringIO()

        env = {
            "BINTU_BASE_URL": "https://service.invalid",
            "BINTU_API_KEY": "offline-service-key",
            "BINTU_SMOKE_TARGET_URL": "https://example.com/",
        }

        with (
            patch.dict(smoke_check.os.environ, env, clear=True),
            patch(
                "smoke_check._request",
                side_effect=responses,
            ),
            patch("smoke_check.check_discovery"),
            patch("smoke_check.check_mcp_cache"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as raised:
                smoke_check.main()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn(expected_message, stderr.getvalue())

        output = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn(SENSITIVE, output)
        self.assertNotIn("offline-service-key", output)
        self.assertNotIn("Smoke check passed.", output)

    def test_health_failures_are_private(self):
        cases = [
            (response(503, {"secret": SENSITIVE}), "HTTP 503"),
            (
                response(200, {"status": SENSITIVE}),
                "unexpected payload",
            ),
            (
                response(200, [SENSITIVE]),
                "unexpected payload",
            ),
            (
                (200, {}, SENSITIVE.encode("utf-8")),
                "invalid JSON",
            ),
            (
                (200, {}, b"\xff" + SENSITIVE.encode("utf-8")),
                "invalid JSON",
            ),
        ]

        for index, (item, message) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_private_failure([item], message)

    def test_scrape_failures_are_private(self):
        cases = [
            (response(502, {"secret": SENSITIVE}), "HTTP 502"),
            (
                response(200, {"secret": SENSITIVE}),
                "empty or missing text",
            ),
            (
                response(200, [SENSITIVE]),
                "unexpected payload",
            ),
            (
                (200, {}, SENSITIVE.encode("utf-8")),
                "invalid JSON",
            ),
        ]

        for index, (item, message) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_private_failure(
                    [successful_prefix()[0], item],
                    message,
                )

    def test_unsafe_url_failures_are_private(self):
        cases = [
            (response(500, {"secret": SENSITIVE}), "HTTP 500"),
            (
                response(400, {"detail": SENSITIVE}),
                "detail is not an object",
            ),
            (
                response(
                    400,
                    {"detail": {"code": SENSITIVE}},
                ),
                "does not use invalid_or_unsafe_url",
            ),
            (
                response(400, [SENSITIVE]),
                "unexpected payload",
            ),
            (
                (400, {}, SENSITIVE.encode("utf-8")),
                "invalid JSON",
            ),
        ]

        for index, (item, message) in enumerate(cases):
            with self.subTest(case=index):
                self.assert_private_failure(
                    successful_prefix() + [item],
                    message,
                )

    def test_metrics_http_failure_is_private(self):
        self.assert_private_failure(
            successful_prefix()
            + [
                response(
                    400,
                    {"detail": {"code": "invalid_or_unsafe_url"}},
                ),
                response(503, {"secret": SENSITIVE}),
            ],
            "/metrics returned HTTP 503.",
        )

    def test_metrics_numeric_failure_is_private(self):
        metrics_body = (
            "bintu_cache_hits_total " + SENSITIVE
        ).encode("utf-8")

        self.assert_private_failure(
            successful_prefix()
            + [
                response(
                    400,
                    {"detail": {"code": "invalid_or_unsafe_url"}},
                ),
                (200, {}, metrics_body),
            ],
            "/metrics returned invalid numeric data.",
        )


if __name__ == "__main__":
    unittest.main()

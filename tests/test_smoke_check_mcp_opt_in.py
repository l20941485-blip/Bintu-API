"""Offline tests for MCP cache opt-in wiring in the smoke script."""

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import smoke_check


class SmokeCheckMcpOptInTests(unittest.TestCase):
    def run_main(self, extra_env=None, helper_error=None):
        env = {
            "BINTU_BASE_URL": "https://service.invalid",
            "BINTU_API_KEY": "offline-service-key",
            "BINTU_SMOKE_TARGET_URL": "https://example.com/",
        }
        env.update(extra_env or {})

        responses = [
            (
                200,
                {},
                json.dumps({"status": "ok"}).encode("utf-8"),
            ),
            (
                200,
                {"X-Request-ID": "offline-request"},
                json.dumps({"text": "Example text"}).encode("utf-8"),
            ),
            (
                400,
                {},
                json.dumps(
                    {"detail": {"code": "invalid_or_unsafe_url"}}
                ).encode("utf-8"),
            ),
        ]

        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = None

        with (
            patch.dict(smoke_check.os.environ, env, clear=True),
            patch(
                "smoke_check._request",
                side_effect=responses,
            ) as request,
            patch("smoke_check._check_metrics") as metrics,
            patch("smoke_check.check_discovery") as discovery,
            patch(
                "smoke_check.check_mcp_cache",
                side_effect=helper_error,
            ) as helper,
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            try:
                smoke_check.main()
            except SystemExit as error:
                exit_code = error.code

        self.assertEqual(request.call_count, 3)
        discovery.assert_called_once_with("https://service.invalid")

        if env["BINTU_API_KEY"].strip():
            metrics.assert_called_once_with(
                "https://service.invalid",
                env["BINTU_API_KEY"].strip(),
            )
        else:
            metrics.assert_not_called()

        return helper, stdout.getvalue(), stderr.getvalue(), exit_code

    def test_unset_flag_skips_helper(self):
        helper, stdout, stderr, exit_code = self.run_main()

        helper.assert_not_called()
        self.assertIn("SKIP MCP cache check", stdout)
        self.assertIn("Smoke check passed.", stdout)
        self.assertEqual(stderr, "")
        self.assertIsNone(exit_code)

    def test_non_one_flags_skip_helper(self):
        for flag in ("", "0", "true", "yes"):
            with self.subTest(flag=flag):
                helper, stdout, stderr, exit_code = self.run_main(
                    {"BINTU_SMOKE_MCP_CACHE": flag}
                )

                helper.assert_not_called()
                self.assertIn("SKIP MCP cache check", stdout)
                self.assertEqual(stderr, "")
                self.assertIsNone(exit_code)

    def test_enabled_flag_falls_back_to_service_key(self):
        helper, stdout, stderr, exit_code = self.run_main(
            {"BINTU_SMOKE_MCP_CACHE": "1"}
        )

        helper.assert_called_once_with(
            "https://service.invalid",
            "offline-service-key",
            "https://example.com/",
        )
        self.assertNotIn("SKIP MCP cache check", stdout)
        self.assertIn("Smoke check passed.", stdout)
        self.assertEqual(stderr, "")
        self.assertIsNone(exit_code)

    def test_scoped_key_takes_priority(self):
        helper, stdout, stderr, exit_code = self.run_main(
            {
                "BINTU_SMOKE_MCP_CACHE": "1",
                "BINTU_MCP_API_KEY": "offline-scoped-key",
            }
        )

        helper.assert_called_once_with(
            "https://service.invalid",
            "offline-scoped-key",
            "https://example.com/",
        )
        self.assertEqual(stderr, "")
        self.assertIsNone(exit_code)

    def test_blank_scoped_key_falls_back_to_service_key(self):
        helper, stdout, stderr, exit_code = self.run_main(
            {
                "BINTU_SMOKE_MCP_CACHE": "1",
                "BINTU_MCP_API_KEY": "   ",
            }
        )

        helper.assert_called_once_with(
            "https://service.invalid",
            "offline-service-key",
            "https://example.com/",
        )
        self.assertEqual(stderr, "")
        self.assertIsNone(exit_code)

    def test_missing_keys_fail_without_calling_helper(self):
        helper, stdout, stderr, exit_code = self.run_main(
            {
                "BINTU_SMOKE_MCP_CACHE": "1",
                "BINTU_API_KEY": "",
            }
        )

        helper.assert_not_called()
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "MCP cache check requires BINTU_MCP_API_KEY or BINTU_API_KEY.",
            stderr,
        )
        self.assertNotIn("Smoke check passed.", stdout)

    def test_helper_failure_does_not_print_exception_message(self):
        sensitive_message = (
            "SENSITIVE upstream body with offline-scoped-key"
        )

        helper, stdout, stderr, exit_code = self.run_main(
            {
                "BINTU_SMOKE_MCP_CACHE": "1",
                "BINTU_MCP_API_KEY": "offline-scoped-key",
            },
            helper_error=RuntimeError(sensitive_message),
        )

        helper.assert_called_once()
        self.assertEqual(exit_code, 1)
        self.assertIn(
            "MCP cache check failed (RuntimeError).",
            stderr,
        )
        self.assertNotIn("Smoke check passed.", stdout)

        combined = stdout + stderr
        self.assertNotIn(sensitive_message, combined)
        self.assertNotIn("offline-scoped-key", combined)
        self.assertNotIn("offline-service-key", combined)


if __name__ == "__main__":
    unittest.main()
import unittest
from unittest import mock

from bintu_api import robots
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings


class RobotsDecisionTests(unittest.TestCase):
    def setUp(self):
        robots.clear_robots_cache()
        self.settings = Settings(api_key="", rapidapi_proxy_secret="")

    def decide(self, url, **patch_kwargs):
        with mock.patch.object(robots, "_fetch_robots_text", **patch_kwargs):
            return robots.robots_decision(url, self.settings)

    def test_missing_robots_allows(self):
        self.assertTrue(self.decide("https://a.example/page", return_value=None).allowed)

    def test_disallowed_path_blocks_but_other_path_allows(self):
        text = "User-agent: *\nDisallow: /private/"
        self.assertFalse(self.decide("https://a.example/private/x", return_value=text).allowed)
        robots.clear_robots_cache()
        self.assertTrue(self.decide("https://a.example/public", return_value=text).allowed)

    def test_unreachable_fails_closed(self):
        decision = self.decide(
            "https://a.example/page", side_effect=robots.RobotsUnreachable("HTTP 503")
        )
        self.assertFalse(decision.allowed)
        self.assertIn("could not be retrieved", decision.reason)

    def test_origins_do_not_share_cache(self):
        with mock.patch.object(
            robots, "_fetch_robots_text", side_effect=["User-agent: *\nDisallow: /", None]
        ):
            first = robots.robots_decision("https://a.example/x", self.settings)
            second = robots.robots_decision("http://a.example/x", self.settings)
        self.assertFalse(first.allowed)
        self.assertTrue(second.allowed)

    def test_second_call_uses_cache(self):
        with mock.patch.object(robots, "_fetch_robots_text", return_value=None) as fetch:
            robots.robots_decision("https://a.example/x", self.settings)
            robots.robots_decision("https://a.example/y", self.settings)
        fetch.assert_called_once()

    def test_unsafe_url_raises_target_rejected(self):
        with self.assertRaises(TargetURLRejected):
            robots.robots_decision("http://example.com:22/", self.settings)


if __name__ == "__main__":
    unittest.main()
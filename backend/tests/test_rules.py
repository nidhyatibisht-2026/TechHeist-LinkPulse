"""Rule-engine tests. Pure: no DB, no network. Run: python -m unittest discover tests"""
import unittest
from datetime import datetime, timedelta, timezone

from app.core.rules import LinkView, Target, Visit, evaluate

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def link(**kw) -> LinkView:
    base = dict(id=1, code="promo", destination="https://example.com")
    base.update(kw)
    return LinkView(**base)


class RuleOrderTests(unittest.TestCase):
    def test_missing_link(self):
        self.assertEqual(evaluate(None, Visit(now=NOW)).action, "not_found")

    def test_archived_link_is_not_found(self):
        self.assertEqual(evaluate(link(status="archived"), Visit(now=NOW)).action, "not_found")

    def test_happy_path_redirects_to_default(self):
        d = evaluate(link(), Visit(now=NOW))
        self.assertEqual((d.action, d.url), ("redirect", "https://example.com"))
        self.assertEqual(len(d.trace), 8)
        self.assertTrue(all(s.passed for s in d.trace))

    def test_disabled_beats_everything(self):
        # Disabled AND expired AND has a fallback: safety must win, no fallback redirect.
        d = evaluate(link(status="disabled", expires_at=NOW - timedelta(days=1),
                          expired_url="https://fallback.example"), Visit(now=NOW))
        self.assertEqual(d.action, "blocked")
        self.assertIsNone(d.url)

    def test_blocklisted_domain_blocks(self):
        d = evaluate(link(), Visit(now=NOW, blocked_domain="example.com"))
        self.assertEqual(d.action, "blocked")

    def test_paused(self):
        self.assertEqual(evaluate(link(status="paused"), Visit(now=NOW)).action, "paused")

    def test_not_started(self):
        d = evaluate(link(starts_at=NOW + timedelta(hours=1)), Visit(now=NOW))
        self.assertEqual(d.action, "not_started")

    def test_expiry_boundary_is_exclusive(self):
        # At exactly expires_at, the link is expired.
        self.assertEqual(evaluate(link(expires_at=NOW), Visit(now=NOW)).action, "expired")
        self.assertEqual(evaluate(link(expires_at=NOW + timedelta(seconds=1)), Visit(now=NOW)).action, "redirect")

    def test_expired_with_fallback_url(self):
        d = evaluate(link(expires_at=NOW - timedelta(days=1), expired_url="https://example.com/ended"),
                     Visit(now=NOW))
        self.assertEqual((d.action, d.url), ("expired", "https://example.com/ended"))

    def test_naive_datetimes_are_treated_as_utc(self):
        naive_past = (NOW - timedelta(hours=1)).replace(tzinfo=None)
        self.assertEqual(evaluate(link(expires_at=naive_past), Visit(now=NOW)).action, "expired")

    def test_cap_reached(self):
        self.assertEqual(evaluate(link(click_cap=10, click_count=10), Visit(now=NOW)).action, "limit")
        self.assertEqual(evaluate(link(click_cap=10, click_count=9), Visit(now=NOW)).action, "redirect")

    def test_cap_checked_before_password(self):
        # A full link should say "limit" instead of asking for a password that cannot help.
        d = evaluate(link(click_cap=5, click_count=5, has_password=True), Visit(now=NOW))
        self.assertEqual(d.action, "limit")

    def test_password_required_and_accepted(self):
        self.assertEqual(evaluate(link(has_password=True), Visit(now=NOW)).action, "password")
        self.assertEqual(evaluate(link(has_password=True), Visit(now=NOW, password_ok=True)).action, "redirect")

    def test_trace_stops_at_failing_rule(self):
        d = evaluate(link(status="paused"), Visit(now=NOW))
        self.assertEqual([s.rule for s in d.trace], ["exists", "safety", "paused"])
        self.assertFalse(d.trace[-1].passed)


class TargetingTests(unittest.TestCase):
    targets = [
        Target("os", "ios", "https://apps.apple.com/app", priority=1),
        Target("os", "android", "https://play.google.com/app", priority=1),
        Target("device", "mobile", "https://m.example.com", priority=2),
        Target("country", "IN", "https://example.in", priority=0),
    ]

    def test_priority_order(self):
        # Country rule has priority 0, so an Indian iPhone user gets the .in site.
        d = evaluate(link(targets=self.targets), Visit(now=NOW, device="mobile", os="ios", country="IN"))
        self.assertEqual(d.url, "https://example.in")

    def test_os_rule(self):
        d = evaluate(link(targets=self.targets), Visit(now=NOW, device="mobile", os="android", country="US"))
        self.assertEqual(d.url, "https://play.google.com/app")

    def test_device_rule_fallback(self):
        d = evaluate(link(targets=self.targets), Visit(now=NOW, device="mobile", os="other", country="US"))
        self.assertEqual(d.url, "https://m.example.com")

    def test_default_for_desktop(self):
        d = evaluate(link(targets=self.targets), Visit(now=NOW, device="desktop", os="windows", country="US"))
        self.assertEqual(d.url, "https://example.com")

    def test_country_match_is_case_insensitive_and_handles_unknown(self):
        d = evaluate(link(targets=self.targets), Visit(now=NOW, country="in"))
        self.assertEqual(d.url, "https://example.in")
        d = evaluate(link(targets=self.targets), Visit(now=NOW, country=None))
        self.assertEqual(d.url, "https://example.com")


if __name__ == "__main__":
    unittest.main()

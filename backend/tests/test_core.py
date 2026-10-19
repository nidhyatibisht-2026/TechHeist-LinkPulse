"""Tests for the other pure modules. Run: python -m unittest discover tests"""
import unittest
from datetime import date

from app.core.agents import detect_bot, parse_agent
from app.core.codes import ALPHABET, alias_problems, generate_code, normalize_alias
from app.core.urls import add_utm, blocked_match, normalize_url, referrer_domain, url_issues
from app.core.visitor import visitor_hash

IPHONE = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
          "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
IPAD = ("Mozilla/5.0 (iPad; CPU OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1")
ANDROID_PHONE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                 "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
ANDROID_TABLET = ("Mozilla/5.0 (Linux; Android 13; SM-X700) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
WIN_EDGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0")
MAC_FIREFOX = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:125.0) Gecko/20100101 Firefox/125.0"
LINUX_CHROME = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36")


class CodeTests(unittest.TestCase):
    def test_generated_codes_use_alphabet_and_length(self):
        for _ in range(200):
            c = generate_code()
            self.assertEqual(len(c), 7)
            self.assertTrue(set(c) <= set(ALPHABET))

    def test_generated_codes_are_valid_aliases(self):
        # Generated codes must pass the same rules users' aliases do (except reserved words).
        for _ in range(200):
            self.assertEqual([p for p in alias_problems(generate_code()) if "reserved" not in p], [])

    def test_alias_rules(self):
        self.assertEqual(alias_problems("summer-sale_2026"), [])
        self.assertTrue(alias_problems("ab"))           # too short
        self.assertTrue(alias_problems("-bad"))         # bad start
        self.assertTrue(alias_problems("bad-"))         # bad end
        self.assertTrue(alias_problems("has space"))
        self.assertTrue(alias_problems("a" * 51))
        self.assertTrue(alias_problems("api"))          # reserved
        self.assertTrue(alias_problems("docs"))

    def test_alias_normalized_to_lowercase(self):
        self.assertEqual(normalize_alias("  Promo "), "promo")
        self.assertIsNone(normalize_alias("   "))


class UrlTests(unittest.TestCase):
    own = {"lnk.example"}

    def codes(self, url, severity="error"):
        return {i.code for i in url_issues(url, "destination", self.own) if i.severity == severity}

    def test_normalize_adds_https(self):
        self.assertEqual(normalize_url(" example.com/x "), "https://example.com/x")
        self.assertEqual(normalize_url("javascript:alert(1)"), "javascript:alert(1)")

    def test_valid_https(self):
        self.assertEqual(url_issues("https://example.com/path?q=1", "destination", self.own), [])

    def test_bad_schemes(self):
        self.assertIn("scheme", self.codes("javascript:alert(1)"))
        self.assertIn("scheme", self.codes("file:///etc/passwd"))
        self.assertIn("scheme", self.codes("data:text/html,hi"))

    def test_private_targets(self):
        self.assertIn("private", self.codes("http://localhost:8000"))
        self.assertIn("private", self.codes("http://127.0.0.1/admin"))
        self.assertIn("private", self.codes("http://192.168.1.1"))
        self.assertIn("private", self.codes("http://169.254.169.254/latest/meta-data"))  # cloud metadata
        self.assertEqual(self.codes("http://8.8.8.8"), set())

    def test_credentials_and_loop(self):
        self.assertIn("credentials", self.codes("https://google.com@evil.com"))
        self.assertIn("loop", self.codes("https://lnk.example/abc"))

    def test_warnings(self):
        self.assertIn("insecure", self.codes("http://example.com", "warning"))
        self.assertIn("punycode", self.codes("https://xn--pple-43d.com", "warning"))

    def test_blocklist_matches_subdomains(self):
        blocked = {"evil.com"}
        self.assertEqual(blocked_match("login.evil.com", blocked), "evil.com")
        self.assertEqual(blocked_match("evil.com", blocked), "evil.com")
        self.assertIsNone(blocked_match("notevil.com", blocked))

    def test_add_utm_merges(self):
        url = add_utm("https://example.com/p?ref=x", {"utm_source": "insta", "utm_medium": "", "utm_campaign": "diwali"})
        self.assertIn("ref=x", url)
        self.assertIn("utm_source=insta", url)
        self.assertIn("utm_campaign=diwali", url)
        self.assertNotIn("utm_medium", url)

    def test_referrer_domain(self):
        self.assertEqual(referrer_domain(None), "Direct")
        self.assertEqual(referrer_domain("https://www.instagram.com/p/1"), "instagram.com")


class AgentTests(unittest.TestCase):
    def test_devices_and_os(self):
        self.assertEqual(parse_agent(IPHONE), parse_agent(IPHONE).__class__("mobile", "ios", "Safari"))
        a = parse_agent(IPAD)
        self.assertEqual((a.device, a.os), ("tablet", "ios"))
        a = parse_agent(ANDROID_PHONE)
        self.assertEqual((a.device, a.os, a.browser), ("mobile", "android", "Chrome"))
        a = parse_agent(ANDROID_TABLET)
        self.assertEqual((a.device, a.os), ("tablet", "android"))
        a = parse_agent(WIN_EDGE)
        self.assertEqual((a.device, a.os, a.browser), ("desktop", "windows", "Edge"))
        a = parse_agent(MAC_FIREFOX)
        self.assertEqual((a.device, a.os, a.browser), ("desktop", "macos", "Firefox"))
        a = parse_agent(LINUX_CHROME)
        self.assertEqual((a.os, a.browser), ("linux", "Chrome"))

    def test_humans_are_not_bots(self):
        for ua in (IPHONE, IPAD, ANDROID_PHONE, ANDROID_TABLET, WIN_EDGE, MAC_FIREFOX, LINUX_CHROME):
            self.assertEqual(detect_bot(ua), (False, None), ua)

    def test_bots(self):
        self.assertEqual(detect_bot("WhatsApp/2.23.20.0 A")[1], "link preview fetcher")
        self.assertEqual(detect_bot("Slackbot-LinkExpanding 1.0 (+https://api.slack.com/robots)")[1],
                         "link preview fetcher")
        self.assertEqual(detect_bot("facebookexternalhit/1.1")[1], "link preview fetcher")
        self.assertEqual(detect_bot("Mozilla/5.0 (compatible; Googlebot/2.1)")[1], "search or AI crawler")
        self.assertEqual(detect_bot("curl/8.4.0")[1], "scripted client")
        self.assertEqual(detect_bot("python-requests/2.31")[1], "scripted client")
        self.assertEqual(detect_bot("")[1], "missing user agent")
        self.assertEqual(detect_bot(LINUX_CHROME.replace("Chrome", "HeadlessChrome"))[1], "headless browser")

    def test_prefetch_header(self):
        self.assertEqual(detect_bot(LINUX_CHROME, {"sec-purpose": "prefetch"}), (True, "browser prefetch"))


class VisitorTests(unittest.TestCase):
    def test_same_day_same_hash_and_rotates_daily(self):
        a = visitor_hash("s", "1.2.3.4", IPHONE, date(2026, 10, 16))
        b = visitor_hash("s", "1.2.3.4", IPHONE, date(2026, 10, 16))
        c = visitor_hash("s", "1.2.3.4", IPHONE, date(2026, 10, 17))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotIn("1.2.3.4", a)


if __name__ == "__main__":
    unittest.main()

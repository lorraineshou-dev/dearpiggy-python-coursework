"""Loopback HTTP integration tests. No API credentials or external calls are used."""

from html import escape
from html.parser import HTMLParser
import http.client
from http.cookies import SimpleCookie
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from ai_chat import ChatService


class Markup(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.tokens = []
        self.elements = []
        self.forms = []
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        self.elements.append((tag, attrs))
        if tag == "input" and attrs.get("name") == "csrf":
            self.tokens.append(attrs.get("value", ""))
        if tag == "form":
            self.forms.append(attrs)


class Browser:
    def __init__(self):
        self.cookie = ""
        self.session = ""
        self.csrf = ""


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fixture_root = Path(self.temporary.name)
        static = self.fixture_root / "static"
        static.mkdir()
        (static / "style.css").write_text("body { color: #123; }", encoding="utf-8")
        (static / "enhance.js").write_text("/* test static asset */", encoding="utf-8")
        # Known synthetic fixtures prove that rejected paths cannot expose an
        # existing file. No real .env file or user's database is accessed.
        self.private_marker = "PRIVATE-HTTP-TEST-FIXTURE"
        (self.fixture_root / ".env.local").write_text(self.private_marker, encoding="utf-8")
        (static / "private.sqlite3").write_text(self.private_marker, encoding="utf-8")
        (self.fixture_root / "outside.css").write_text(self.private_marker, encoding="utf-8")
        self.symlink_supported = True
        try:
            (static / "escape.css").symlink_to(self.fixture_root / "outside.css")
        except (OSError, NotImplementedError):
            self.symlink_supported = False
        self.root_patch = patch.object(main, "ROOT", self.fixture_root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.requester = Mock(side_effect=AssertionError("No external AI call is allowed in HTTP tests"))
        self._start()

    def _start(self):
        self.chat = ChatService(key="", requester=self.requester)
        self.server = main.make_server(0, self.fixture_root / "data", chat_service=self.chat)
        self.host = f"127.0.0.1:{self.server.server_port}"
        self.origin = "http://" + self.host
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.server.application.store.close()

    def tearDown(self):
        self._stop()
        self.requester.assert_not_called()

    def request(self, method="GET", path="/", *, browser=None, fields=None, body=None, headers=None):
        # Explicit Host also lets malformed absolute targets reach the server
        # instead of being rejected first by http.client's Host generation.
        request_headers = {"Host": self.host}
        if browser and browser.cookie:
            request_headers["Cookie"] = browser.cookie
        if fields is not None:
            body = urlencode(fields).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        if method == "POST":
            request_headers["Origin"] = self.origin
        request_headers.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        try:
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            raw = response.read()
            result = SimpleNamespace(status=response.status, headers={k.lower(): v for k, v in response.getheaders()}, body=raw, text=raw.decode("utf-8", errors="replace"))
        finally:
            connection.close()
        if browser:
            if "set-cookie" in result.headers:
                cookie = SimpleCookie(result.headers["set-cookie"])
                browser.session = cookie[main.COOKIE_NAME].value
                browser.cookie = main.COOKIE_NAME + "=" + browser.session
            markup = Markup(result.text)
            if markup.tokens:
                browser.csrf = markup.tokens[0]
        return result

    def visitor(self):
        browser = Browser()
        response = self.request(browser=browser)
        self.assertEqual(response.status, 200)
        self.assertRegex(browser.session, r"^[a-f0-9]{64}$")
        self.assertRegex(browser.csrf, r"^[a-f0-9]{64}$")
        return browser, response

    def action(self, browser, action, **fields):
        return self.request("POST", "/action", browser=browser,
                            fields={"csrf": browser.csrf, "action": action, "next": "/", **fields})

    def state(self, browser):
        return self.server.application.store.get(browser.session)

    def test_welcome_forms_and_cookie_have_safe_defaults(self):
        browser, response = self.visitor()
        self.assertIn('class="welcome-page"', response.text)
        self.assertIn('name="action" value="welcome"', response.text)
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=Strict", response.headers["set-cookie"])
        self.assertIn("Path=/", response.headers["set-cookie"])
        markup = Markup(response.text)
        self.assertTrue(markup.forms)
        self.assertTrue(all(form.get("method") == "post" and form.get("action") == "/action" for form in markup.forms))
        self.assertEqual(set(markup.tokens), {browser.csrf})
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertIn("form-action 'self'", response.headers["content-security-policy"])
        self.assertFalse(self.state(browser)["welcomed"])

    def test_welcome_and_game_progress_survive_server_restart(self):
        browser, _ = self.visitor()
        response = self.action(browser, "welcome")
        self.assertEqual((response.status, response.headers["location"]), (303, "/"))
        self.assertTrue(self.state(browser)["welcomed"])
        self.assertEqual(self.action(browser, "complete", id="water", next="/care").status, 303)
        self.assertEqual(self.state(browser)["energy"], 10)
        old_token, old_session = browser.csrf, browser.session
        self._stop()
        self._start()
        page = self.request(browser=browser)
        self.assertEqual(page.status, 200)
        self.assertEqual(browser.session, old_session)
        self.assertNotEqual(browser.csrf, old_token)
        self.assertNotIn('class="welcome-page"', page.text)
        self.assertEqual((self.state(browser)["energy"], self.state(browser)["total"]), (10, 1))
        rejected = self.request("POST", "/action", browser=browser,
                                fields={"csrf": old_token, "action": "complete", "id": "kind"})
        self.assertEqual(rejected.status, 403)
        self.assertEqual(self.state(browser)["energy"], 10)

    def test_missing_wrong_unicode_and_foreign_session_csrf_are_rejected(self):
        first, _ = self.visitor()
        second, _ = self.visitor()
        before = self.state(first)
        for token in ("", "wrong", "f" * 64, "雪", second.csrf):
            with self.subTest(token=token):
                response = self.request("POST", "/action", browser=first,
                                        fields={"csrf": token, "action": "complete", "id": "water"})
                self.assertEqual(response.status, 403)
                self.assertEqual(self.state(first), before)
        response = self.request("POST", "/action", fields={"csrf": first.csrf, "action": "welcome"})
        self.assertEqual(response.status, 403)

    def test_host_origin_and_cross_site_rejections_do_not_mutate_state(self):
        browser, _ = self.visitor()
        before = self.state(browser)
        bad_headers = [
            {"Host": "evil.invalid"}, {"Host": "127.0.0.1"},
            {"Origin": "https://evil.invalid"}, {"Origin": "null"},
            {"Origin": "http://localhost:" + str(self.server.server_port)},
            {"Sec-Fetch-Site": "cross-site"},
        ]
        for headers in bad_headers:
            with self.subTest(headers=headers):
                response = self.request("POST", "/action", browser=browser, headers=headers,
                                        fields={"csrf": browser.csrf, "action": "complete", "id": "water"})
                self.assertEqual(response.status, 403)
                self.assertEqual(self.state(browser), before)
        self.assertEqual(self.request(headers={"Host": "evil.invalid"}).status, 403)
        local_alias = self.request(headers={"Host": "localhost:" + str(self.server.server_port)})
        self.assertEqual(local_alias.status, 200)

    def test_unknown_and_sensitive_paths_are_not_served(self):
        browser, _ = self.visitor()
        paths = ["/missing", "/main.py", "/catalogue.json", "/.env.local", "/data/piggy.sqlite3",
                 "/data/piggy.sqlite3-wal", "/static/private.sqlite3", "/static/../.env.local",
                 "/static/%2e%2e/.env.local", "/static/%2e%2e%2fdata%2fpiggy.sqlite3",
                 "/static/%252e%252e/.env.local", "/static/.hidden.css"]
        if self.symlink_supported:
            paths.append("/static/escape.css")
        for path in paths:
            with self.subTest(path=path):
                response = self.request(path=path, browser=browser)
                self.assertEqual(response.status, 404)
                self.assertNotIn(self.private_marker, response.text)
                self.assertNotIn("SQLite format", response.text)
        self.assertEqual(self.request("POST", "/missing", browser=browser, fields={"csrf": browser.csrf}).status, 404)

    def test_static_assets_and_head_requests(self):
        css = self.request(path="/static/style.css")
        self.assertEqual(css.status, 200)
        self.assertIn("text/css", css.headers["content-type"])
        self.assertEqual(css.text, "body { color: #123; }")
        javascript = self.request(path="/static/enhance.js")
        self.assertEqual(javascript.headers["content-type"], "text/javascript")
        head = self.request("HEAD", "/static/style.css")
        self.assertEqual(head.status, 200)
        self.assertEqual(head.body, b"")
        self.assertEqual(int(head.headers["content-length"]), len(css.body))

    def test_malformed_paths_fail_cleanly(self):
        for path in ("/static/%00.css", "http://[invalid"):
            with self.subTest(path=path):
                response = self.request(path=path)
                self.assertIn(response.status, (400, 404))

    def test_redirects_remain_local_and_safe(self):
        browser, _ = self.visitor()
        unsafe = ["https://evil.invalid/", "//evil.invalid/", "javascript:alert(1)", "/missing",
                  "/care\r\nX-Injected: yes", "/%2f%2fevil.invalid", "http://[invalid",
                  "/care?" + "x" * 2100]
        for target in unsafe:
            with self.subTest(target=target):
                response = self.action(browser, "welcome", next=target)
                self.assertEqual((response.status, response.headers.get("location")), (303, "/"))
                self.assertNotIn("x-injected", response.headers)
        safe = "/shop?preview=coat&slot=clothes"
        response = self.action(browser, "welcome", next=safe)
        self.assertEqual((response.status, response.headers["location"]), (303, safe))
        response = self.action(browser, "welcome", next="/care?category=雪")
        self.assertEqual(response.status, 303)
        self.assertTrue(response.headers["location"].startswith("/"))
        response.headers["location"].encode("ascii")

    def test_malicious_profile_and_habit_text_is_escaped(self):
        browser, _ = self.visitor()
        self.action(browser, "welcome")
        name = '<img src=x onerror=1>'
        nickname = '<svg onload=alert(1)>'
        habit = 'x"><script>alert(1)</script>'
        self.assertEqual(self.action(browser, "profile", name=name, nickname=nickname).status, 303)
        self.assertEqual(self.action(browser, "add_habit", title=habit, category="mind").status, 303)
        for path, text in (("/", name), ("/settings", name), ("/settings", nickname), ("/care", habit)):
            with self.subTest(path=path, text=text):
                page = self.request(path=path, browser=browser)
                self.assertEqual(page.status, 200)
                self.assertIn(escape(text), page.text)
                self.assertNotIn(text, page.text)
                markup = Markup(page.text)
                self.assertFalse(any("onerror" in attrs or "onload" in attrs for _, attrs in markup.elements))
                self.assertTrue(all(attrs.get("src", "").startswith("/static/") for tag, attrs in markup.elements if tag == "script"))
        self.assertEqual(self.state(browser)["name"], name)
        self.assertEqual(self.state(browser)["habits"][-1]["en"], habit)

    def test_sessions_are_separate_and_cookie_tampering_is_replaced(self):
        first, _ = self.visitor()
        second, _ = self.visitor()
        self.assertNotEqual(first.session, second.session)
        self.assertNotEqual(first.csrf, second.csrf)
        self.action(first, "welcome")
        self.action(first, "complete", id="water")
        self.action(first, "save_journal", mood="calm", note="First browser private moment")
        self.assertEqual(self.state(second)["energy"], 0)
        self.assertEqual(self.state(second)["journal"], [])
        self.assertFalse(self.state(second)["welcomed"])
        self.assertNotIn("First browser private moment", self.request(path="/feelings", browser=second).text)
        tampered = Browser()
        tampered.cookie = main.COOKIE_NAME + "=malformed"
        response = self.request(browser=tampered)
        self.assertEqual(response.status, 200)
        self.assertRegex(tampered.session, r"^[a-f0-9]{64}$")
        self.assertNotIn(tampered.session, (first.session, second.session))

    def test_unconfigured_chat_does_not_persist_or_call_ai(self):
        browser, _ = self.visitor()
        self.action(browser, "welcome")
        before = self.state(browser)
        draft = '<script>alert("private draft")</script>'
        response = self.request("POST", "/chat", browser=browser,
                                fields={"csrf": browser.csrf, "message": draft})
        self.assertEqual(response.status, 200)
        self.assertIn("AI chat is not configured", response.text)
        self.assertNotIn(draft, response.text)
        self.assertEqual(self.chat.history(browser.session), [])
        self.assertEqual(self.state(browser), before)
        self.requester.assert_not_called()
        clear = self.request("POST", "/chat/clear", browser=browser, fields={"csrf": browser.csrf})
        self.assertEqual((clear.status, clear.headers["location"]), (303, "/chat"))
        self.assertEqual(self.state(browser), before)
        second, _ = self.visitor()
        self.assertNotIn("private draft", self.request(path="/chat", browser=second).text)

    def test_invalid_forms_and_unknown_actions_do_not_change_progress(self):
        browser, _ = self.visitor()
        before = self.state(browser)
        duplicate = urlencode([("csrf", browser.csrf), ("action", "complete"), ("id", "water"), ("id", "kind")])
        cases = [
            (duplicate.encode(), {"Content-Type": "application/x-www-form-urlencoded"}),
            (b"{}", {"Content-Type": "application/json"}),
            (b"\xff", {"Content-Type": "application/x-www-form-urlencoded"}),
            (b"x", {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(main.MAX_BODY + 1)}),
            (b"", {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": "0"}),
        ]
        for body, headers in cases:
            with self.subTest(headers=headers):
                response = self.request("POST", "/action", browser=browser, body=body, headers=headers)
                self.assertEqual(response.status, 400)
                self.assertEqual(self.state(browser), before)
        response = self.action(browser, "set_energy", energy="9999")
        self.assertEqual(response.status, 303)
        self.assertEqual(self.state(browser), before)

    def test_all_pages_render_and_shop_preview_does_not_purchase(self):
        browser, _ = self.visitor()
        self.action(browser, "welcome")
        before = self.state(browser)
        for path in ("/", "/care", "/feelings", "/breathe", "/chat", "/shop", "/growth", "/settings",
                     "/shop?preview=coat&slot=clothes", "/?pose=wave"):
            with self.subTest(path=path):
                response = self.request(path=path, browser=browser)
                self.assertEqual(response.status, 200)
                self.assertIn("<!doctype html", response.text.lower())
        self.assertEqual(self.state(browser), before)


if __name__ == "__main__":
    unittest.main()

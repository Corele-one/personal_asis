import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest

from personal_asis.coordinator import Coordinator
from personal_asis.pwa import server
from personal_asis.web_auth import WebAuth


class PwaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.http = server(self.home, port=0, origin="https://example.test", auth_method="password")
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.cookie, self.csrf = "", ""

    def request(self, path, body=None, headers=None):
        base = {"Host": "example.test", "X-Forwarded-Proto": "https", "Origin": "https://example.test"}
        if self.cookie: base["Cookie"] = self.cookie
        if body is not None: base.update({"Content-Type": "application/json", "X-CSRF-Token": self.csrf})
        base.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        conn.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, base)
        response = conn.getresponse()
        raw = response.read()
        result = json.loads(raw) if response.getheader("Content-Type").startswith("application/json") else raw
        status, returned = response.status, dict(response.getheaders())
        conn.close()
        return status, result, returned

    def login(self):
        with WebAuth(self.home, otp_required=False) as auth:
            setup = auth.bootstrap()["setup_token"]
        self.assertEqual(self.request("/auth/setup/start", {"setup_token": setup})[0], 200)
        status, result, headers = self.request("/auth/setup/finish", {"setup_token": setup, "password": "synthetic-password-for-test", "code": ""})
        self.assertEqual(status, 200)
        self.cookie = headers["Set-Cookie"].split(";", 1)[0]
        self.csrf = result["csrf"]
        return headers

    def test_authentication_tls_origin_csrf_and_cookie_requirements(self):
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.request("/", headers={"X-Forwarded-Proto": "http"})[0], 403)
        self.assertEqual(self.request("/", headers={"Host": "attacker.test"})[0], 403)
        headers = self.login()
        for option in ("Secure", "HttpOnly", "SameSite=Strict", "Path=/"):
            self.assertIn(option, headers["Set-Cookie"])
        self.assertEqual(self.request("/api/state")[0], 200)
        data = {"query": "合成芯片", "request_id": "fixture-request"}
        self.assertEqual(self.request("/api/search", data, {"Origin": "https://attacker.test"})[0], 403)
        self.assertEqual(self.request("/api/search", data, {"X-CSRF-Token": "wrong"})[0], 403)
        self.assertEqual(self.request("/api/search", data)[0], 200)

    def test_search_idempotency_offline_state_audit_and_logout(self):
        self.login()
        data = {"query": "合成芯片", "request_id": "fixture-request"}
        first = self.request("/api/search", data)[1]
        second = self.request("/api/search", data)[1]
        self.assertEqual(first["task_id"], second["task_id"])
        view = self.request("/api/tasks/" + first["task_id"])[1]
        self.assertTrue(view["partial"])
        self.assertEqual(view["waiting_nodes"], ["mac"])
        self.assertNotIn("合成芯片", json.dumps(self.request("/api/audit")[1], ensure_ascii=False))
        self.assertEqual(self.request("/auth/logout", {})[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_static_shell_has_no_private_api_cache_or_external_scripts(self):
        status, shell, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn(b"https://", shell)
        worker = self.request("/sw.js")[1]
        self.assertNotIn(b"'/api/", worker)
        self.assertNotIn(b"'/auth/", worker)


if __name__ == "__main__": unittest.main()

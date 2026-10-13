from pathlib import Path
import tempfile
import unittest

from personal_asis.coordinator import ProtocolError
from personal_asis.web_auth import WebAuth, otp


class WebAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.time = 1000
        self.addCleanup(self.tmp.cleanup)

    def auth(self, totp=False):
        return WebAuth(self.home, clock=lambda: self.time, otp_required=totp)

    def configured(self, totp=False):
        with self.auth(totp) as auth:
            token = auth.bootstrap()["setup_token"]
            start = auth.setup_start(token, "fixture-client")
            code = otp(start["secret"], int(self.time // 30)) if totp else ""
            result = auth.setup_finish(token, "synthetic-long-password", code, "fixture-client")
        return result, start, token

    def test_rfc6238_sha1_vectors(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        for at, expected in ((59, "94287082"), (1111111109, "07081804"), (20000000000, "65353130")):
            self.assertEqual(otp(secret, at // 30, 8), expected)

    def test_static_password_setup_sessions_logout_and_no_plaintext_storage(self):
        result, start, setup = self.configured()
        self.assertFalse(start["otp_required"])
        with self.auth() as auth:
            self.assertTrue(auth.initialized())
            self.assertTrue(auth.session(result["token"], result["csrf"])["authenticated"])
            with self.assertRaises(ProtocolError): auth.session(result["token"], "wrong-csrf")
            with self.assertRaises(ProtocolError): auth.setup_start(setup, "fixture-client")
            login = auth.login("synthetic-long-password", "", "fixture-client")
            row = auth.db.execute("SELECT * FROM owner").fetchone()
            self.assertNotIn("synthetic-long-password", str(tuple(row)))
            self.assertIsNone(row["otp_secret"])
            auth.logout(login["token"])
            with self.assertRaises(ProtocolError): auth.session(login["token"])

    def test_totp_replay_rejected_and_next_step_accepted(self):
        _, start, _ = self.configured(totp=True)
        with self.auth(True) as auth:
            code = otp(start["secret"], int(self.time // 30))
            with self.assertRaises(ProtocolError): auth.login("synthetic-long-password", code, "fixture-client")
            self.time += 30
            result = auth.login("synthetic-long-password", otp(start["secret"], int(self.time // 30)), "fixture-client")
            self.assertTrue(auth.session(result["token"])["authenticated"])

    def test_failures_rate_limit_and_setup_expiry(self):
        self.configured()
        with self.auth() as auth:
            for _ in range(5):
                with self.assertRaises(ProtocolError): auth.login("invalid-synthetic-password", "", "attacker")
            with self.assertRaises(ProtocolError) as context:
                auth.login("synthetic-long-password", "", "attacker")
            self.assertEqual(context.exception.status, 429)
            self.time += 901
            self.assertIn("token", auth.login("synthetic-long-password", "", "attacker"))
            setup = auth.bootstrap(reset=True)["setup_token"]
            self.time += 3601
            with self.assertRaises(ProtocolError): auth.setup_start(setup, "fixture-client")

    def test_idle_expiry_and_admin_reset_revoke_sessions(self):
        result, _, _ = self.configured()
        self.time += 1801
        with self.auth() as auth:
            with self.assertRaises(ProtocolError): auth.session(result["token"])
            token = auth.login("synthetic-long-password", "", "fixture-client")["token"]
            auth.bootstrap(reset=True)
            with self.assertRaises(ProtocolError): auth.session(token)
            self.assertFalse(auth.initialized())


if __name__ == "__main__": unittest.main()

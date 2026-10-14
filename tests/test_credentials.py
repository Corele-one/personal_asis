import json
import subprocess
import unittest
from unittest.mock import patch

from personal_asis.credentials import CredentialStore


class CredentialTests(unittest.TestCase):
    def test_wsl_uses_windows_store_without_secret_in_argv(self):
        secret = "synthetic-test-secret"
        responses = [subprocess.CompletedProcess([], 0, b"F:\\repo\\wincred.ps1\n"),
                     subprocess.CompletedProcess([], 0, b'{"stored":true}')]
        with patch.object(CredentialStore, "_is_wsl", return_value=True), \
             patch("personal_asis.credentials.sys.platform", "linux"), \
             patch("personal_asis.credentials.subprocess.run", side_effect=responses) as run:
            CredentialStore("rog@test").set(secret)
        command = run.call_args.args[0]
        self.assertNotIn(secret, " ".join(command))
        payload = json.loads(run.call_args.kwargs["input"])
        self.assertEqual(payload["secret"], secret)
        self.assertEqual(payload["action"], "set")

    def test_wsl_error_never_exposes_bridge_output(self):
        responses = [subprocess.CompletedProcess([], 0, b"F:\\repo\\wincred.ps1\n"),
                     subprocess.CompletedProcess([], 2, b"sensitive stdout", b"sensitive stderr")]
        with patch("personal_asis.credentials.subprocess.run", side_effect=responses):
            with self.assertRaises(ValueError) as error:
                CredentialStore("rog@test")._windows_wsl()
        self.assertNotIn("sensitive", str(error.exception))

    def test_wsl_get_validates_response(self):
        for payload in (b'{"secret":"synthetic"}', b'{"secret":""}', b'{}', b'bad-json'):
            responses = [subprocess.CompletedProcess([], 0, b"F:\\repo\\wincred.ps1\n"),
                         subprocess.CompletedProcess([], 0, payload)]
            with self.subTest(payload=payload), \
                 patch("personal_asis.credentials.subprocess.run", side_effect=responses):
                if payload == b'{"secret":"synthetic"}':
                    self.assertEqual(CredentialStore("rog@test")._windows_wsl(), "synthetic")
                else:
                    with self.assertRaises(ValueError):
                        CredentialStore("rog@test")._windows_wsl()

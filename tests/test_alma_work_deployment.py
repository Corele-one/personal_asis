"""Deployment boundaries, with no network or private configuration reads."""
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "deploy" / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class AlmaDeploymentTests(unittest.TestCase):
    def test_provider_update_preserves_identity_models_and_user_settings(self):
        config = module("configure-alma-work")
        providers = [dict(id="existing-mimo", name="Work MiMo (existing VPS account)",
            baseURL="https://api.xiaomimimo.com/v1", models=["user-added-model"],
            availableModels=[dict(id="user-added-model", name="User choice")]),
            dict(id="existing-deepseek", name="DeepSeek", baseURL="https://api.deepseek.com/v1",
            models=[], availableModels=[])]
        calls = []

        def api(path, method="GET", body=None):
            calls.append((path, method, body))
            if path == "/api/providers" and method == "GET":
                return providers
            for provider in providers:
                if path == "/api/providers/" + provider["id"]:
                    return {**provider, **body}
                if path == "/api/providers/" + provider["id"] + "/models":
                    return {**provider, **body}
            self.fail("Unexpected API call: " + path)

        with patch.object(config, "api", side_effect=api):
            result = config.configure_providers()
        self.assertEqual(result["xiaomi"]["id"], "existing-mimo")
        self.assertEqual(result["deepseek"]["id"], "existing-deepseek")
        update = next(body for path, method, body in calls if path.endswith("existing-mimo/models"))
        self.assertIn("user-added-model", update["models"])
        self.assertIn("mimo-v2.6-flash", update["models"])
        self.assertTrue(any(m["id"] == "user-added-model" for m in update["availableModels"]))
        for model_id in ("mimo-v2.6-flash", "deepseek-v4-flash"):
            model = next(model for path, method, body in calls
                if path.endswith("/models") for model in body["availableModels"]
                if model["id"] == model_id)
            self.assertEqual(model["capabilityOverrides"]["contextWindow"], 1_000_000)
            self.assertEqual(model["capabilityOverrides"]["maxOutputTokens"], 4096)
        self.assertFalse(any(path == "/api/settings" for path, method, body in calls))

    def test_stderr_never_returns_untrusted_error_or_secret(self):
        runner = module("run-alma-work")
        chunks = [b"private request and synthetic-secret-token: heap out of mem",
            b"ory; upstream private content\n", b"heap out of memory", b"EADDRINUSE"]
        self.assertEqual(list(runner.diagnostic_labels(chunks)),
            ["v8_heap_exhausted", "listener_port_in_use"])
        self.assertEqual(list(runner.diagnostic_labels([b"unknown private upstream body"])), [])

    def test_wrong_archive_rejected_before_identity_or_filesystem_changes(self):
        installer = module("install-alma-work")
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "not-official.tar.gz"
            archive.write_bytes(b"synthetic corrupted archive")
            with patch.object(installer, "run", side_effect=[
                types.SimpleNamespace(stdout="0"), types.SimpleNamespace(stdout="x86_64")]), \
                patch.object(installer.pwd, "getpwnam") as identity, \
                self.assertRaisesRegex(SystemExit, "archive_digest_mismatch"):
                installer.install(archive, Path(directory) / "unit")
            identity.assert_not_called()


if __name__ == "__main__":
    unittest.main()

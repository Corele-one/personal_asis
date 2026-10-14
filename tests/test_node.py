import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from personal_asis.config import load_config
from personal_asis.coordinator import Coordinator
from personal_asis.index import Index
from personal_asis.node import Client, Poller, connection_config, policy_hash
from personal_asis.transport import server


class MemoryStore:
    def __init__(self):
        self.secret = None

    def get(self):
        if self.secret is None:
            raise ValueError("missing")
        return self.secret

    def set(self, value):
        self.secret = value


class NodeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.dbpath = self.base / "coordinator.sqlite3"
        self.http = server(self.dbpath, port=0)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.endpoint = f"http://127.0.0.1:{self.http.server_port}"

    def node(self, name):
        home = self.base / name
        home.mkdir()
        (home / "Note").mkdir()
        (home / "Daily").mkdir()
        (home / "Note" / "same.md").write_text("# 合成芯片\n共同测试证据\n")
        (home / "Note" / "sensitive.md").write_text("---\nsensitivity: private\n---\n# SECRET_TITLE\n芯片 PRIVATE_SENTINEL\n")
        (home / "Daily" / "daily.md").write_text("# DAILY_SECRET\n芯片 DAILY_SENTINEL\n")
        config = {"node_id": name, "sources": [
            {"id": "note", "root": str(home / "Note"), "policy": "normal", "remote_metadata": True},
            {"id": "daily", "root": str(home / "Daily"), "policy": "private"}]}
        (home / "sources.yaml").write_text(json.dumps(config))
        (home / "coordinator.json").write_text(json.dumps({"endpoint": self.endpoint, "transport": "ssh_tunnel"}))
        with Index(home / "index.sqlite3", load_config(home / "sources.yaml")) as index:
            index.reconcile()
        with Coordinator(self.dbpath) as c:
            code = c.pair(name)["pairing_code"]
        client = Client(connection_config(home), name, store=MemoryStore())
        client.enroll(code)
        poller = Poller(home, client)
        self.addCleanup(poller.close)
        return home, poller

    def submit(self, request="request1", channel="pwa"):
        with Coordinator(self.dbpath) as c:
            return c.submit("芯片", channel, 20, request)["task_id"]

    def view(self, task):
        with Coordinator(self.dbpath) as c:
            return c.view(task)

    def test_two_nodes_real_http_partial_completion_and_no_sensitive_payload(self):
        _, mac = self.node("mac")
        _, rog = self.node("rog")
        task = self.submit()
        mac.once()
        self.assertEqual(self.view(task)["waiting_nodes"], ["rog"])
        rog.once()
        view = self.view(task)
        self.assertFalse(view["partial"])
        self.assertEqual(len(view["results"]), 1)
        self.assertEqual(len(view["results"][0]["replicas"]), 2)
        stored = "".join(p.read_bytes().decode(errors="ignore") for p in self.base.glob("coordinator.sqlite3*"))
        for forbidden in ("PRIVATE_SENTINEL", "SECRET_TITLE", "DAILY_SECRET", "共同测试证据", str(self.base)):
            self.assertNotIn(forbidden, stored)

    def test_http_authentication_and_unknown_metadata_fields(self):
        _, mac = self.node("mac")
        with self.assertRaises(HTTPError) as context:
            mac.client.request("/v1/poll", {"policy_hash": "a" * 64})
        self.assertEqual(context.exception.code, 401)
        context.exception.close()
        with self.assertRaises(HTTPError) as context:
            mac.client.authenticated("/v1/poll", {"policy_hash": "a" * 64, "root": "/secret"})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()

    def test_outbox_recovers_lost_http_response_after_restart(self):
        home, mac = self.node("mac")
        task = self.submit()
        original = mac.client.authenticated
        def lose_reply(route, data):
            value = original(route, data)
            if route == "/v1/complete":
                raise OSError("lost_reply")
            return value
        mac.client.authenticated = lose_reply
        with self.assertRaises(OSError):
            mac.once()
        self.assertEqual(mac.db.execute("SELECT count(*) FROM outbox").fetchone()[0], 1)
        mac.client.authenticated = original
        restarted = Poller(home, mac.client)
        try:
            restarted.once()
            self.assertEqual(restarted.db.execute("SELECT count(*) FROM outbox").fetchone()[0], 0)
        finally:
            restarted.close()
        with Coordinator(self.dbpath) as c:
            events = c.audit()["events"]
        self.assertEqual(sum(e["kind"] == "completed" and e["task_id"] == task for e in events), 1)

    def test_revoked_local_source_clears_vps_results_on_next_poll(self):
        home, mac = self.node("mac")
        task = self.submit()
        mac.once()
        path = home / "sources.yaml"
        config = json.loads(path.read_text())
        config["sources"][0]["remote_metadata"] = False
        path.write_text(json.dumps(config))
        mac.once()
        self.assertEqual(self.view(task)["results"], [])

    def test_document_classification_change_clears_old_results_after_reconcile(self):
        home, mac = self.node("mac")
        task = self.submit()
        mac.once()
        (home / "Note" / "same.md").write_text("---\nsensitivity: private\n---\n# 合成芯片\n共同测试证据\n")
        with Index(home / "index.sqlite3", load_config(home / "sources.yaml")) as index:
            index.reconcile()
        mac.once()
        self.assertEqual(self.view(task)["results"], [])

    def test_lost_response_outbox_never_resends_a_newly_private_document(self):
        home, mac = self.node("mac")
        task = self.submit()
        original = mac.client.authenticated
        def fail_before_send(route, data):
            if route == "/v1/complete":
                raise OSError("offline")
            return original(route, data)
        mac.client.authenticated = fail_before_send
        with self.assertRaises(OSError):
            mac.once()
        (home / "Note" / "same.md").write_text("---\nsensitivity: private\n---\n# 合成芯片\n共同测试证据\n")
        mac.client.authenticated = original
        mac.once()
        self.assertEqual(self.view(task)["results"], [])
        self.assertEqual(mac.db.execute("SELECT count(*) FROM outbox").fetchone()[0], 0)

    def test_feishu_payload_is_metadata_only(self):
        _, mac = self.node("mac")
        task = self.submit(channel="feishu")
        mac.once()
        text = json.dumps(self.view(task))
        for field in ("excerpt", "original_uri", "line_start", "PRIVATE_SENTINEL"):
            self.assertNotIn(field, text)

    def test_remote_path_allowlist_revocation_clears_cached_metadata(self):
        home, mac = self.node("mac")
        path = home / "sources.yaml"
        config = json.loads(path.read_text())
        config["sources"][0]["remote_metadata_paths"] = ["same.md"]
        path.write_text(json.dumps(config))
        task = self.submit()
        mac.once()
        self.assertEqual(len(self.view(task)["results"]), 1)
        before = policy_hash(load_config(path))
        config["sources"][0]["remote_metadata_paths"] = []
        path.write_text(json.dumps(config))
        self.assertNotEqual(before, policy_hash(load_config(path)))
        mac.once()
        self.assertEqual(self.view(task)["results"], [])

    def test_extraction_coverage_changes_invalidate_coordinator_snapshots(self):
        home, mac = self.node("mac")
        path = home / "sources.yaml"
        config = json.loads(path.read_text())
        config["sources"][0]["formats"] = ["md", "docx"]
        path.write_text(json.dumps(config))
        task = self.submit()
        mac.once()
        self.assertFalse(self.view(task)["coverage_incomplete"])
        broken = home / "Note" / "broken.docx"
        broken.write_bytes(b"not a valid document")
        with Index(home / "index.sqlite3", load_config(path)) as index:
            index.reconcile()
        mac.once()
        self.assertEqual(self.view(task)["coverage"][0]["skipped_documents"], 1)
        broken.unlink()
        with Index(home / "index.sqlite3", load_config(path)) as index:
            index.reconcile()
        mac.once()
        self.assertFalse(self.view(task)["coverage_incomplete"])

    def test_endpoint_rejects_public_http_and_credential_urls(self):
        home = self.base / "validation"
        home.mkdir()
        path = home / "coordinator.json"
        for endpoint in ("http://35.209.202.207:8765", "https://user:pass@example.com", "https://example.com/path"):
            path.write_text(json.dumps({"endpoint": endpoint, "transport": "ssh_tunnel"}))
            with self.assertRaises(ValueError):
                connection_config(home)


if __name__ == "__main__":
    unittest.main()

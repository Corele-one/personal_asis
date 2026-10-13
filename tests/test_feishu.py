import asyncio
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from personal_asis.coordinator import Coordinator, ProtocolError
from personal_asis.feishu import FeishuBridge, summary, view_digest


class FeishuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.time = 1000
        self.b = FeishuBridge(self.home, lambda: self.time)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.b.close)

    def bind(self, sender="ou_owner"):
        code = self.b.pairing("lark-fixture")["pairing_code"]
        self.assertTrue(self.b.bind("lark-fixture", sender, code))
        return code

    def test_binding_one_time_expiring_and_platform_bound(self):
        code = self.b.pairing("lark-fixture")["pairing_code"]
        self.assertFalse(self.b.bind("qq-fixture", "ou_other", code))
        self.assertFalse(self.b.bind("lark-fixture", "qq_id", code))
        self.time += 601
        self.assertFalse(self.b.bind("lark-fixture", "ou_other", code))
        code = self.bind()
        self.assertFalse(self.b.bind("lark-fixture", "ou_other", code))
        self.assertTrue(self.b.authorized("lark-fixture", "ou_owner"))
        self.assertFalse(self.b.authorized("lark-fixture", "ou_other"))

    def test_sender_whitelist_and_message_idempotency(self):
        with self.assertRaises(ProtocolError):
            self.b.submit("lark-fixture", "ou_owner", "message-1", "芯片")
        self.bind()
        task = self.b.submit("lark-fixture", "ou_owner", "message-1", "芯片")
        self.assertEqual(self.b.submit("lark-fixture", "ou_owner", "message-1", "芯片"), task)
        with self.assertRaises(ProtocolError):
            self.b.submit("lark-fixture", "ou_other", "message-2", "芯片")
        self.assertEqual(self.b.view("lark-fixture", "ou_owner", task)["channel"], "feishu")
        with self.assertRaises(ProtocolError):
            self.b.view("lark-fixture", "ou_owner", str(uuid.uuid4()))

    def test_summary_ignores_evidence_and_body_fields(self):
        view = {"task_id": str(uuid.uuid4()), "partial": True, "waiting_nodes": ["rog"],
                "nodes": [{"node_id": "rog", "state": "waiting_for_node"}],
                "results": [{"replicas": [{"title": "合成芯片", "node_id": "mac", "source_id": "note",
                    "path_hint": "test.md", "excerpt": "SECRET_BODY", "original_uri": "file:///SECRET_ROOT"}]}]}
        text = summary(view)
        self.assertIn("部分结果", text)
        self.assertIn("等待节点：rog", text)
        self.assertIn("合成芯片", text)
        self.assertNotIn("SECRET_BODY", text)
        self.assertNotIn("SECRET_ROOT", text)
        linked = summary(view, "https://example.test")
        self.assertIn("https://example.test/#task=", linked)
        self.assertNotIn("SECRET_BODY", linked)

    def test_completion_notifies_once_and_unknown_send_is_not_repeated(self):
        self.bind()
        task = self.b.submit("lark-fixture", "ou_owner", "message-1", "芯片")
        route, view, digest = self.b.pending()[0]
        calls = []
        async def send(*args):
            calls.append(args)
            return True
        self.assertEqual(asyncio.run(self.b.deliver(route, view, digest, send)), "sent")
        self.assertEqual(asyncio.run(self.b.deliver(route, view, digest, send)), "sent")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.b.pending(), [])
        with Coordinator(self.home / "coordinator.sqlite3", nodes=("mac",)) as c:
            job = c.poll("mac", "a" * 64)["job"]
            c.complete("mac", task, job["lease"], {"node_id": "mac", "channel": "feishu", "hits": [],
                       "sources": [{"source_id": "note", "status": "ready"}], "stale_candidates_skipped": 0})
        route, view, digest = self.b.pending()[0]
        async def lost(*args):
            calls.append(args)
            raise OSError("reply outcome unknown")
        self.assertEqual(asyncio.run(self.b.deliver(route, view, digest, lost)), "unknown")
        restarted = FeishuBridge(self.home, lambda: self.time)
        try:
            self.assertEqual(asyncio.run(restarted.deliver(route, view, digest, lost)), "unknown")
            self.assertEqual(restarted.pending(), [])
        finally:
            restarted.close()
        self.assertEqual(len(calls), 2)

    def test_rebinding_revokes_old_task_routes(self):
        self.bind()
        task = self.b.submit("lark-fixture", "ou_owner", "message-1", "芯片")
        self.bind("ou_new_owner")
        with self.assertRaises(ProtocolError):
            self.b.view("lark-fixture", "ou_owner", task)
        self.assertEqual(self.b.pending(), [])

    def test_bridge_state_contains_no_query_plaintext(self):
        self.bind()
        self.b.submit("lark-fixture", "ou_owner", "message-1", "QUERY_PRIVATE_SENTINEL")
        tables = [list(self.b.db.execute(f"SELECT * FROM {table}")) for table in ("binding", "routes", "deliveries")]
        self.assertNotIn("QUERY_PRIVATE_SENTINEL", str(tables))


if __name__ == "__main__":
    unittest.main()

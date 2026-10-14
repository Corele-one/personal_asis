import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from personal_asis.coordinator import Coordinator, ProtocolError, fingerprint


def result(node="mac", channel="pwa", waiting=False, hits=True):
    return {"node_id": node, "channel": channel, "hits": [{
        "node_id": node, "source_id": "note", "document_id": str(uuid.uuid4()),
        "content_hash": "a" * 64, "title": "合成芯片", "path_hint": "note.md",
        "indexed_at": "2026-10-13T00:00:00+00:00", "index_version": 1}] if hits else [],
        "sources": [{"source_id": "note", "status": "ready"},
                    {"source_id": "daily", "status": "waiting_for_source" if waiting else "ready"}],
        "stale_candidates_skipped": 0}


class CoordinatorTests(unittest.TestCase):
    def test_default_registration_and_search_use_only_mac(self):
        with Coordinator(self.path.with_name("mac-only.sqlite3")) as coordinator:
            self.assertEqual([row[0] for row in coordinator.db.execute("SELECT id FROM nodes")], ["mac"])
            with self.assertRaises(ProtocolError):
                coordinator.pair("rog")
            task = coordinator.submit("synthetic query", "pwa", 20, "mac-only-default")["task_id"]
            self.assertEqual([node["node_id"] for node in coordinator.view(task)["nodes"]], ["mac"])

    def test_disabled_node_leaves_old_and_new_search_scope_and_can_resume(self):
        code = self.c.pair("rog")["pairing_code"]
        self.c.enroll("rog", code, "r" * 43)
        token = self.c.session("rog", "r" * 43)["token"]
        task = self.task()
        mac, rog = self.claim("mac"), self.claim("rog")
        self.c.complete("mac", task, mac["lease"], result("mac"))
        self.c.complete("rog", task, rog["lease"], result("rog"))
        self.c.set_enabled("rog", False)
        with self.assertRaises(ProtocolError):
            self.c.authenticate(token)
        old = self.c.view(task)
        self.assertFalse(old["partial"])
        self.assertEqual([node["node_id"] for node in old["nodes"]], ["mac"])
        self.assertEqual([hit["node_id"] for group in old["results"] for hit in group["replicas"]], ["mac"])
        self.assertIsNone(self.c.db.execute("SELECT result FROM jobs WHERE task_id=? AND node_id='rog'", (task,)).fetchone()[0])
        new = self.task("mac-only")
        self.assertEqual([node["node_id"] for node in self.c.view(new)["nodes"]], ["mac"])
        self.c.set_enabled("rog", True)
        self.assertEqual(self.c.authenticate(self.c.session("rog", "r"*43)["token"]), "rog")

    def test_skipped_text_files_are_visible_without_revealing_paths(self):
        task = self.task()
        job = self.claim()
        payload = result()
        payload["sources"][0]["skipped_documents"] = 7
        self.c.complete("mac", task, job["lease"], payload)
        view = self.c.view(task)
        self.assertTrue(view["coverage_incomplete"])
        self.assertEqual(view["coverage"], [{"node_id": "mac", "source_id": "note", "skipped_documents": 7}])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "coordinator.sqlite3"
        self.time = 1000
        self.c = Coordinator(self.path, nodes=("mac", "rog"), clock=lambda: self.time)
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.c.db.close)

    def task(self, request="request1"):
        return self.c.submit("芯片", "pwa", 20, request)["task_id"]

    def claim(self, node="mac", policy="b" * 64):
        return self.c.poll(node, policy)["job"]

    def test_pairing_single_use_expiry_and_session_rotation(self):
        code = self.c.pair("mac")["pairing_code"]
        self.c.enroll("mac", code, "c" * 43)
        self.assertTrue(self.c.enroll("mac", code, "c" * 43)["enrolled"])
        with self.assertRaises(ProtocolError):
            self.c.enroll("mac", code, "d" * 43)
        token = self.c.session("mac", "c" * 43)["token"]
        self.assertEqual(self.c.authenticate(token), "mac")
        token2 = self.c.session("mac", "c" * 43)["token"]
        with self.assertRaises(ProtocolError):
            self.c.authenticate(token)
        self.time += 301
        with self.assertRaises(ProtocolError):
            self.c.authenticate(token2)
        code2 = self.c.pair("rog")["pairing_code"]
        self.time += 601
        with self.assertRaises(ProtocolError):
            self.c.enroll("rog", code2, "c" * 43)
        stored = self.c.db.execute("SELECT credential_hash FROM nodes WHERE id='mac'").fetchone()[0]
        self.assertEqual(stored, fingerprint("c" * 43))

    def test_idempotency_and_restart(self):
        task = self.task()
        self.assertEqual(self.task(), task)
        with self.assertRaises(ProtocolError):
            self.c.submit("different", "pwa", 20, "request1")
        job = self.claim()
        with Coordinator(self.path, clock=lambda: self.time) as restarted:
            self.assertIsNone(restarted.poll("mac", "b" * 64)["job"])
            self.assertEqual(restarted.view(task)["nodes"][0]["state"], "running")
        self.assertEqual(self.c.db.execute("SELECT count(*) FROM tasks").fetchone()[0], 1)
        self.assertEqual(job["task_id"], task)

    def test_new_unanswered_query_precedes_historical_revalidation_without_losing_old_work(self):
        historical=self.task('historical')
        job=self.claim()
        self.c.complete('mac',historical,job['lease'],result())
        self.time+=1
        active=self.task('active-new-query')
        job=self.claim(policy='c'*64)
        self.assertEqual(job['task_id'],active)
        self.assertEqual(self.c.view(historical)['results'],[])
        self.c.complete('mac',active,job['lease'],result())
        self.assertEqual(self.claim(policy='c'*64)['task_id'],historical)

    def test_concurrent_pollers_cannot_claim_the_same_live_lease(self):
        self.task()
        barrier = threading.Barrier(2)
        claims, failures = [], []
        def poll():
            try:
                with Coordinator(self.path, clock=lambda: self.time) as other:
                    barrier.wait(timeout=5)
                    claims.append(other.poll("mac", "b" * 64)["job"])
            except Exception as exc:
                failures.append(exc)
        threads = [threading.Thread(target=poll) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(failures)
        self.assertEqual(sum(c is not None for c in claims), 1)

    def test_offline_partial_recovery_and_replica_group(self):
        task = self.task()
        job = self.claim()
        payload = result()
        self.c.complete("mac", task, job["lease"], payload)
        view = self.c.view(task)
        self.assertTrue(view["partial"])
        self.assertEqual(view["waiting_nodes"], ["rog"])
        self.assertEqual(view["nodes"][1]["state"], "waiting_for_node")
        self.time += 100
        job2 = self.claim("rog")
        self.c.complete("rog", task, job2["lease"], result("rog"))
        view = self.c.view(task)
        self.assertFalse(view["partial"])
        self.assertEqual(len(view["results"]), 1)
        replicas = view["results"][0]["replicas"]
        self.assertEqual({r["node_id"] for r in replicas}, {"mac", "rog"})
        self.assertEqual(len({r["document_id"] for r in replicas}), 2)

    def test_expired_lease_and_wrong_owner_rejected(self):
        task = self.task()
        old = self.claim()
        self.time += 121
        new = self.claim()
        self.assertNotEqual(old["lease"], new["lease"])
        with self.assertRaises(ProtocolError):
            self.c.complete("mac", task, old["lease"], result())
        with self.assertRaises(ProtocolError):
            self.c.complete("rog", task, new["lease"], result())
        self.c.complete("mac", task, new["lease"], result())

    def test_lost_completion_reply_is_idempotent(self):
        task, payload = self.task(), result()
        job = self.claim()
        self.c.complete("mac", task, job["lease"], payload)
        self.time += 500
        self.assertTrue(self.c.complete("mac", task, job["lease"], payload)["duplicate"])
        payload["hits"][0]["title"] = "different"
        with self.assertRaises(ProtocolError):
            self.c.complete("mac", task, job["lease"], payload)

    def test_source_offline_keeps_partial_and_retries(self):
        task = self.task()
        job = self.claim()
        self.c.complete("mac", task, job["lease"], result(waiting=True))
        self.assertEqual(self.c.view(task)["nodes"][0]["state"], "waiting_for_source")
        self.assertIsNone(self.claim())
        self.time += 60
        retry = self.claim()
        self.c.complete("mac", task, retry["lease"], result())
        self.assertEqual(self.c.view(task)["waiting_nodes"], ["rog"])

    def test_policy_revision_invalidates_cached_metadata_and_leases(self):
        task = self.task()
        job = self.claim()
        self.c.complete("mac", task, job["lease"], result())
        next_job = self.claim(policy="f" * 64)
        self.assertEqual(next_job["task_id"], task)
        self.assertEqual(self.c.view(task)["results"], [])
        with self.assertRaises(ProtocolError):
            self.c.complete("mac", task, job["lease"], result())

    def test_strict_metadata_rejects_text_and_absolute_paths(self):
        task = self.task()
        job = self.claim()
        for change in ({"excerpt": "PRIVATE SENTINEL"}, {"path_hint": "/private/file.md"},
                       {"path_hint": "../file.md"}, {"node_id": "rog"}):
            payload = result()
            payload["hits"][0].update(change)
            with self.assertRaises(ProtocolError):
                self.c.complete("mac", task, job["lease"], payload)
        self.assertNotIn("PRIVATE SENTINEL", self.path.read_bytes().decode(errors="ignore"))
        self.assertNotIn("芯片", json.dumps(self.c.audit(), ensure_ascii=False))

    def test_revocation_invalidates_credentials_and_results(self):
        code = self.c.pair("mac")["pairing_code"]
        self.c.enroll("mac", code, "c" * 43)
        token = self.c.session("mac", "c" * 43)["token"]
        task, job = self.task(), self.claim()
        self.c.complete("mac", task, job["lease"], result())
        self.c.revoke("mac")
        with self.assertRaises(ProtocolError):
            self.c.authenticate(token)
        self.assertEqual(self.c.view(task)["results"], [])


if __name__ == "__main__":
    unittest.main()

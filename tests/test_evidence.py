import base64
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from personal_asis.config import load_config
from personal_asis.coordinator import ProtocolError
from personal_asis.evidence import Relay, context, encrypt, control_server
from personal_asis.index import Index
from personal_asis.pwa import server as pwa_server
import test_node as node_tests
import test_pwa as pwa_tests


CRYPTO = importlib.util.find_spec("cryptography") is not None


def keys():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, base64.b64encode(public).decode()


def decrypt(envelope, key, job):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    decode = lambda name: base64.b64decode(envelope[name])
    aes = key.decrypt(decode("wrapped_key"), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return json.loads(AESGCM(aes).decrypt(decode("nonce"), decode("ciphertext"), context(job)))


class RelayTests(unittest.TestCase):
    def request(self):
        return {"node_id": "mac", "document_id": "00000000-0000-4000-8000-000000000001", "content_hash": "a"*64,
                "mode": "text", "cursor": 0, "client_nonce": base64.b64encode(b"n"*16).decode(),
                "public_key": base64.b64encode(b"p"*294).decode(), "query": "synthetic"}

    def test_finite_memory_bound_node_leases_expiry_and_revocation(self):
        now = [0]
        relay = Relay(clock=lambda: now[0])
        request = relay.request(self.request())
        self.assertIsNone(relay.poll("rog")["job"])
        job = relay.poll("mac")["job"]
        self.assertIsNone(relay.poll("mac")["job"])
        completion = {"request_id": request["request_id"], "lease": job["lease"], "status": "denied", "envelope": None}
        with self.assertRaises(ProtocolError):
            relay.complete("rog", completion)
        now[0] = 46
        with self.assertRaises(ProtocolError):
            relay.complete("mac", completion)
        job = relay.poll("mac")["job"]
        completion["lease"] = job["lease"]
        relay.complete("mac", completion)
        self.assertEqual(relay.get(request["request_id"])["status"], "denied")
        now[0] = 91
        with self.assertRaises(ProtocolError):
            relay.get(request["request_id"])
        for _ in range(32):
            relay.request(self.request())
        with self.assertRaises(ProtocolError):
            relay.request(self.request())
        relay.invalidate("mac")
        self.assertEqual(relay.jobs, {})

    def test_plaintext_and_unknown_fields_rejected(self):
        relay = Relay()
        with self.assertRaises(ProtocolError):
            relay.request({**self.request(), "text": "never store this"})
        request = relay.request(self.request())
        job = relay.poll("mac")["job"]
        with self.assertRaises(ProtocolError):
            relay.complete("mac", {"request_id": request["request_id"], "lease": job["lease"], "status": "ready",
                "envelope": {"text": "plaintext"}})

    def test_idle_server_removes_expired_ciphertext_without_new_requests(self):
        relay = Relay(ttl=.05)
        with tempfile.TemporaryDirectory() as directory:
            server, path = control_server(directory, relay)
            try:
                relay.request(self.request())
                deadline = time.monotonic() + 3
                while relay.jobs and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertEqual(relay.jobs, {})
            finally:
                server.shutdown()
                server.server_close()
                path.unlink()

    @unittest.skipUnless(CRYPTO, "requires reader dependency")
    def test_authenticated_encryption_binds_document_version_mode_and_cursor(self):
        from cryptography.exceptions import InvalidTag
        key, public = keys()
        job = {**self.request(), "public_key": public}
        value = {"text": "合成证据 ENCRYPTED_BODY_CANARY", "locator": {"page": 2}}
        envelope = encrypt(value, job)
        self.assertEqual(decrypt(envelope, key, job), value)
        self.assertNotIn("ENCRYPTED_BODY_CANARY", json.dumps(envelope))
        for field, changed in (("cursor", 1), ("content_hash", "b"*64), ("mode", "excerpt")):
            with self.assertRaises(InvalidTag):
                decrypt(envelope, key, {**job, field: changed})

    @unittest.skipUnless(CRYPTO and shutil.which("node"), "requires reader dependency and Node WebCrypto")
    def test_browser_webcrypto_decrypts_python_envelope(self):
        from cryptography.hazmat.primitives import serialization
        key, public = keys()
        job = {**self.request(), "public_key": public}
        private = key.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        value = {"text": "WebCrypto 中文 😀 proof"}
        program = r"""
const {webcrypto}=require('node:crypto');let raw='';process.stdin.on('data',c=>raw+=c);process.stdin.on('end',async()=>{
 const d=JSON.parse(raw),s=webcrypto.subtle,b=x=>Buffer.from(x,'base64');
 const k=await s.importKey('pkcs8',b(d.key),{name:'RSA-OAEP',hash:'SHA-256'},false,['decrypt']);
 const aes=await s.importKey('raw',await s.decrypt({name:'RSA-OAEP'},k,b(d.envelope.wrapped_key)),'AES-GCM',false,['decrypt']);
 const text=await s.decrypt({name:'AES-GCM',iv:b(d.envelope.nonce),additionalData:b(d.context)},aes,b(d.envelope.ciphertext));
 process.stdout.write(Buffer.from(text));});
"""
        result = subprocess.run(["node", "-e", program], input=json.dumps({"key": base64.b64encode(private).decode(),
            "envelope": encrypt(value, job), "context": base64.b64encode(context(job)).decode()}),
            capture_output=True, text=True, timeout=15, check=True)
        self.assertEqual(json.loads(result.stdout), value)


@unittest.skipUnless(CRYPTO, "requires reader dependency")
class ReaderFlowTests(unittest.TestCase):
    node, submit, view = node_tests.NodeTests.node, node_tests.NodeTests.submit, node_tests.NodeTests.view
    request, login = pwa_tests.PwaTests.request, pwa_tests.PwaTests.login

    def setUp(self):
        node_tests.NodeTests.setUp(self)
        self.coordinator_http = self.http
        self.home, self.mac = self.node("mac")
        self.config_path = self.home / "sources.yaml"
        config = json.loads(self.config_path.read_text())
        config["sources"][0]["remote_evidence"] = True
        self.config_path.write_text(json.dumps(config))
        self.task = self.submit()
        self.mac.once()
        self.hit = self.view(self.task)["results"][0]["replicas"][0]
        self.assertTrue(self.hit["reader_allowed"])
        # The real PWA and node HTTP services share a private Unix relay only.
        self.home, self.node_home = self.base, self.home
        self.http = pwa_server(self.base, port=0, origin="https://example.test", auth_method="password")
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.cookie, self.csrf = "", ""
        self.key, public = keys()
        self.job = {"task_id": self.task, "document_id": self.hit["document_id"], "content_hash": self.hit["content_hash"],
            "mode": "text", "cursor": 0, "client_nonce": base64.b64encode(b"n"*16).decode(), "public_key": public}

    def test_owner_auth_csrf_encrypted_node_reader_and_no_vps_plaintext(self):
        self.assertEqual(self.request("/api/reader/request", self.job)[0], 401)
        self.login()
        self.assertEqual(self.request("/api/reader/request", self.job, {"X-CSRF-Token": "wrong"})[0], 403)
        status, request, headers = self.request("/api/reader/request", self.job)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.mac.once()
        status, result, _ = self.request("/api/reader/result", {"request_id": request["request_id"]})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ready")
        value = decrypt(result["envelope"], self.key, self.job)
        self.assertIn("共同测试证据", value["text"])
        stored = b"".join(p.read_bytes() for p in self.base.glob("*.sqlite3*"))
        self.assertNotIn("共同测试证据".encode(), stored)
        self.assertNotIn(b"PRIVATE_SENTINEL", stored)
        self.assertEqual(self.mac.db.execute("SELECT count(*) FROM outbox").fetchone()[0], 0)

    def test_stale_private_and_revoked_local_policy_never_return_text(self):
        config = load_config(self.config_path)
        with Index(self.node_home / "index.sqlite3", config) as index:
            private = index.db.execute("SELECT document_id,content_hash FROM documents WHERE path='sensitive.md'").fetchone()
            job = {**self.job, "document_id": private[0], "content_hash": private[1]}
            self.assertEqual(index.reader(job), {"status": "denied"})
            # A private metadata exception never becomes a body permission.
            index.config = replace(config, sources=tuple(replace(s, private_remote_metadata=True) for s in config.sources))
            self.assertEqual(index.reader(job), {"status": "denied"})
            (self.node_home / "Note" / "same.md").write_text("changed on disk before reconciliation")
            self.assertEqual(index.reader(self.job), {"status": "stale"})
        self.login()
        self.assertEqual(self.request("/api/reader/request", {**self.job, "document_id": private[0]})[0], 403)
        # Revoke reader permission: the next heartbeat invalidates the RAM relay.
        request = self.request("/api/reader/request", self.job)[1]
        data = json.loads(self.config_path.read_text())
        data["sources"][0]["remote_evidence"] = False
        self.config_path.write_text(json.dumps(data))
        self.mac.once()
        self.assertEqual(self.request("/api/reader/result", {"request_id": request["request_id"]})[0], 404)

    def test_reader_chunks_are_bounded_and_locations_preserved(self):
        path = self.node_home / "Note" / "same.md"
        path.write_text("# 合成芯片\n" + "synthetic😀\n" * 1600)
        config = load_config(self.config_path)
        with Index(self.node_home / "index.sqlite3", config) as index:
            index.reconcile()
            row = index.db.execute("SELECT * FROM documents WHERE path='same.md'").fetchone()
            job = {**self.job, "content_hash": row["content_hash"], "query": "synthetic"}
            first = index.reader(job)["value"]
            self.assertEqual(len(first["text"]), 6000)
            self.assertEqual(first["next_cursor"], 6000)
            second = index.reader({**job, "cursor": 6000})["value"]
            self.assertGreater(second["locator"]["line"], 1)
            self.assertEqual(first["text"] + second["text"], path.read_text()[:12000])
            minimal = index.reader({**job, "mode": "excerpt"})["value"]
            self.assertLessEqual(len(minimal["text"]), 240)


if __name__ == "__main__":
    unittest.main()

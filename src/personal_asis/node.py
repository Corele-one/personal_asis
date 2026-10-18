"""Outbound node transport and durable, policy-filtered completion outbox."""

import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request

from .config import load_config
from .coordinator import metadata_result
from .credentials import CredentialStore
from .index import Index


def connection_config(home):
    data = json.loads((home / "coordinator.json").read_text())
    endpoint = data.get("endpoint")
    if not isinstance(endpoint, str):
        raise ValueError("协调服务需要显式配置 endpoint")
    url = urlsplit(endpoint)
    if url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("endpoint 必须是无凭据、无路径的服务地址")
    if url.scheme == "https" and url.hostname:
        pass
    elif (url.scheme == "http" and url.hostname == "127.0.0.1"
          and data.get("transport") == "ssh_tunnel" and url.port):
        pass
    else:
        raise ValueError("只允许验证证书的 HTTPS，或显式配置的 127.0.0.1 SSH 隧道")
    return endpoint.rstrip("/")


def policy_hash(config):
    # Includes roots/exclusions and source enable flags so revocations invalidate caches.
    data = [(s.id, str(s.root), s.policy, s.index, s.remote_metadata, s.private_remote_metadata,
             s.exclude, s.private_paths, s.remote_metadata_paths, s.formats, s.remote_evidence,
             s.private_remote_evidence, s.reading_cache) for s in config.sources]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def node_policy_hash(home, config):
    # Index reconciliation also changes document-level classification/availability.
    # Export a digest only; no document identity or private metadata in heartbeats.
    with Index(home / "index.sqlite3", config) as index:
        documents = [tuple(r) for r in index.db.execute("""SELECT document_id,source_id,
            content_hash,policy FROM documents WHERE active=1 ORDER BY document_id""")]
        sources = [tuple(r) for r in index.db.execute("SELECT id,available FROM sources ORDER BY id")]
        failures = [tuple(r) for r in index.db.execute(
            "SELECT source_id,path,signature,reason FROM extraction_failures ORDER BY source_id,path")]
    return hashlib.sha256(json.dumps([policy_hash(config), documents, sources, failures]).encode()).hexdigest()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_):
        return None  # Credentials must never follow redirects to another origin.


class Client:
    def __init__(self, endpoint, node_id, store=None, clock=time.monotonic):
        self.endpoint, self.node_id, self.clock = endpoint, node_id, clock
        self.store = store or CredentialStore(f"{node_id}@{endpoint}")
        self.token, self.expires = None, 0
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route, data, token=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(self.endpoint + route, json.dumps(data).encode(), headers, method="POST")
        with self.opener.open(req, timeout=15) as response:
            raw = response.read(512 * 1024 + 1)
            if len(raw) > 512 * 1024:
                raise ValueError("协调服务响应超过协议限制")
            return json.loads(raw)

    def enroll(self, code):
        # Reuse an existing saved secret to recover from a lost enrollment response.
        try:
            credential = self.store.get()
        except (ValueError, FileNotFoundError, subprocess.SubprocessError):
            credential = secrets.token_urlsafe(32)
            self.store.set(credential)
        return self.request("/v1/enroll", {"node_id": self.node_id, "pairing_code": code, "credential": credential})

    def authenticated(self, route, data):
        for attempt in range(2):
            if self.token is None or self.clock() >= self.expires:
                result = self.request("/v1/session", {"node_id": self.node_id, "credential": self.store.get()})
                self.token = result["token"]
                self.expires = self.clock() + result["expires_in"] - 10
            try:
                return self.request(route, data, self.token)
            except HTTPError as exc:
                if exc.code != 401 or attempt:
                    raise
                exc.close()
                self.token = None


def search_result(home, job):
    # Load source policy again at execution, never rely on a remote permission flag.
    config = load_config(home / "sources.yaml")
    with Index(home / "index.sqlite3", config) as index:
        result = index.search(job["query"], job["channel"], job["limit"])
    payload = {"node_id": config.node_id, "channel": job["channel"],
               "hits": [h for group in result["results"] for h in group["replicas"]],
               "sources": [{"source_id": s["source_id"], "status": s["status"],
                            "skipped_documents": s.get("skipped_documents", 0)} for s in result["sources"]],
               "stale_candidates_skipped": result["stale_candidates_skipped"]}
    metadata_result(payload, config.node_id, job["channel"])
    return payload


class Poller:
    def __init__(self, home, client=None):
        self.home = Path(home)
        config = load_config(self.home / "sources.yaml")
        self.client = client or Client(connection_config(self.home), config.node_id)
        self.node_id = config.node_id
        path = self.home / "node-tasks.sqlite3"
        self.db = sqlite3.connect(path, timeout=30)
        os.chmod(path, 0o600)
        self.db.execute("""CREATE TABLE IF NOT EXISTS outbox (
            task_id TEXT PRIMARY KEY, lease TEXT NOT NULL, policy_hash TEXT NOT NULL,
            result TEXT NOT NULL, created REAL NOT NULL)""")
        self.db.execute("DELETE FROM outbox WHERE created < ?", (time.time() - 180 * 86400,))
        self.db.commit()

    def close(self):
        self.db.close()

    def _reader_once(self, config):
        if not any(s.remote_evidence for s in config.sources):
            return False
        from .evidence import encrypt
        response = self.client.authenticated("/v1/evidence/poll", {})
        job = response["job"]
        if job is None:
            return False
        before = node_policy_hash(self.home, config)
        with Index(self.home / "index.sqlite3", config) as index:
            value = index.reader(job)
        status, envelope = value["status"], None
        if node_policy_hash(self.home, load_config(self.home / "sources.yaml")) != before:
            status = "denied"
        elif status == "ready":
            try:
                envelope = encrypt(value["value"], job)
            except (ImportError, ValueError, TypeError):
                status = "failed"
        self.client.authenticated("/v1/evidence/complete", {"request_id": job["request_id"], "lease": job["lease"],
            "status": status, "envelope": envelope})
        return True

    def once(self):
        config = load_config(self.home / "sources.yaml")
        if config.node_id != self.node_id:
            raise ValueError("已配对的 node_id 变化，需重新配置连接")
        stamp = node_policy_hash(self.home, config)
        # Policy revocations must reach the server before an old outbox can be replayed.
        poll = self.client.authenticated("/v1/poll", {"policy_hash": stamp})
        with self.db:
            self.db.execute("DELETE FROM outbox WHERE policy_hash!=?", (stamp,))
        job = poll["job"]
        self._reader_once(config)
        # Retry a persisted completion if a previous reply was lost.
        for task_id, lease, _, result, _ in self.db.execute("SELECT * FROM outbox").fetchall():
            payload = json.loads(result)
            # A restart cannot resend a title/path that has since become private,
            # disappeared or changed version, even before scheduled reconciliation.
            with Index(self.home / "index.sqlite3", config) as index:
                allowed = {(h["document_id"], h["content_hash"]) for h in index.catalog()["documents"]}
            if any((h["document_id"], h["content_hash"]) not in allowed for h in payload["hits"]):
                with self.db:
                    self.db.execute("DELETE FROM outbox WHERE task_id=?", (task_id,))
                continue
            try:
                self.client.authenticated("/v1/complete", {"task_id": task_id, "lease": lease, "result": payload})
            except HTTPError as exc:
                if exc.code != 409:
                    raise
            with self.db:
                self.db.execute("DELETE FROM outbox WHERE task_id=?", (task_id,))
        if job is None:
            return {"event": "poll", "claimed": False}
        # Reject a policy race between poll and search before sending any result.
        result = search_result(self.home, job)
        if node_policy_hash(self.home, load_config(self.home / "sources.yaml")) != stamp:
            return {"event": "poll", "claimed": True, "policy_changed": True}
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO outbox VALUES(?,?,?,?,?)",
                            (job["task_id"], job["lease"], stamp, json.dumps(result), time.time()))
        self.client.authenticated("/v1/complete", {"task_id": job["task_id"], "lease": job["lease"], "result": result})
        with self.db:
            self.db.execute("DELETE FROM outbox WHERE task_id=?", (job["task_id"],))
        return {"event": "poll", "claimed": True, "completed": True, "task_id": job["task_id"]}

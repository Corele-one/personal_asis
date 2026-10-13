"""Durable PA0 scheduling. Only allowlisted metadata can enter the database."""

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import uuid

from .index import group_replicas


class ProtocolError(ValueError):
    def __init__(self, code, status=400):
        super().__init__(code)
        self.status = status


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", value):
        raise ProtocolError("invalid_identifier")
    return value


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ProtocolError("invalid_fields")


def metadata_result(value, node_id, channel):
    """Reject unknown keys, including text, excerpts and absolute file URIs."""
    exact(value, ("node_id", "channel", "hits", "sources", "stale_candidates_skipped"))
    if value["node_id"] != node_id or value["channel"] != channel:
        raise ProtocolError("result_owner_mismatch")
    hits, sources = value["hits"], value["sources"]
    if not isinstance(hits, list) or len(hits) > 100 or not isinstance(sources, list) or len(sources) > 100:
        raise ProtocolError("invalid_result_size")
    for hit in hits:
        exact(hit, ("document_id", "content_hash", "title", "node_id", "source_id",
                    "path_hint", "indexed_at", "index_version"))
        try:
            if str(uuid.UUID(hit["document_id"])) != hit["document_id"]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise ProtocolError("invalid_document_id") from None
        if hit["node_id"] != node_id:
            raise ProtocolError("result_owner_mismatch")
        identifier(hit["source_id"])
        if not isinstance(hit["content_hash"], str) or not re.fullmatch(r"[0-9a-f]{64}", hit["content_hash"]):
            raise ProtocolError("invalid_content_hash")
        for field in ("title", "path_hint", "indexed_at"):
            if not isinstance(hit[field], str) or len(hit[field]) > 1024 or any(ord(c) < 32 for c in hit[field]):
                raise ProtocolError("invalid_metadata_string")
        path = hit["path_hint"]
        if not path or path.startswith(("/", "\\")) or "\\" in path or ":" in path or ".." in Path(path).parts:
            raise ProtocolError("invalid_path_hint")
        if type(hit["index_version"]) is not int or hit["index_version"] < 1:
            raise ProtocolError("invalid_index_version")
    seen = set()
    for source in sources:
        exact(source, ("source_id", "status"))
        identifier(source["source_id"])
        if source["source_id"] in seen or source["status"] not in {"ready", "disabled", "waiting_for_source"}:
            raise ProtocolError("invalid_source_status")
        seen.add(source["source_id"])
    ready = {s["source_id"] for s in sources if s["status"] == "ready"}
    if any(h["source_id"] not in ready for h in hits):
        raise ProtocolError("unavailable_hit")
    if type(value["stale_candidates_skipped"]) is not int or value["stale_candidates_skipped"] < 0:
        raise ProtocolError("invalid_stale_count")
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
 id TEXT PRIMARY KEY, credential_hash TEXT, last_seen REAL,
 policy_hash TEXT, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS pairings (
 code_hash TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(id), expires REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, query TEXT NOT NULL,
 channel TEXT NOT NULL, result_limit INTEGER NOT NULL, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
 task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
 node_id TEXT NOT NULL REFERENCES nodes(id), state TEXT NOT NULL DEFAULT 'queued',
 lease TEXT, lease_until REAL, retry_at REAL NOT NULL DEFAULT 0,
 result TEXT, result_hash TEXT, policy_hash TEXT,
 PRIMARY KEY(task_id,node_id)
);
CREATE TABLE IF NOT EXISTS events (
 sequence INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, node_id TEXT,
 kind TEXT NOT NULL, at REAL NOT NULL
);
"""


class Coordinator:
    def __init__(self, path, nodes=("mac", "rog"), clock=time.time,
                 session_ttl=300, lease_ttl=120, offline_after=90, retention=180 * 86400):
        self.clock, self.session_ttl, self.lease_ttl = clock, session_ttl, lease_ttl
        self.offline_after, self.retention = offline_after, retention
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        with self.transaction():
            for node in nodes:
                self.db.execute("INSERT OR IGNORE INTO nodes(id) VALUES(?)", (identifier(node),))
            cutoff = self.clock() - retention
            self.db.execute("DELETE FROM tasks WHERE created < ?", (cutoff,))
            self.db.execute("DELETE FROM events WHERE at < ?", (cutoff,))
            self.db.execute("DELETE FROM sessions WHERE expires <= ?", (self.clock(),))
            self.db.execute("DELETE FROM pairings WHERE expires <= ?", (self.clock(),))

    def transaction(self):
        # BEGIN IMMEDIATE makes lease claims and one-time pairing atomic across processes.
        from contextlib import contextmanager
        @contextmanager
        def tx():
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
        return tx()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def event(self, kind, task_id=None, node_id=None):
        self.db.execute("INSERT INTO events(task_id,node_id,kind,at) VALUES(?,?,?,?)",
                        (task_id, node_id, kind, self.clock()))

    def pair(self, node_id):
        identifier(node_id)
        code = secrets.token_urlsafe(32)
        with self.transaction():
            node = self.db.execute("SELECT * FROM nodes WHERE id=? AND enabled=1", (node_id,)).fetchone()
            if node is None:
                raise ProtocolError("unknown_node", 404)
            self.db.execute("DELETE FROM pairings WHERE node_id=?", (node_id,))
            self.db.execute("INSERT INTO pairings VALUES(?,?,?)", (fingerprint(code), node_id, self.clock() + 600))
        return {"node_id": node_id, "pairing_code": code, "expires_in": 600}

    def enroll(self, node_id, code, credential):
        # Client generates and saves its secret before enrollment: a lost HTTP response
        # cannot lose the only usable copy of the node credential.
        if not all(isinstance(s, str) and 32 <= len(s) <= 128 for s in (code, credential)):
            raise ProtocolError("invalid_pairing")
        with self.transaction():
            pairing = self.db.execute("SELECT * FROM pairings WHERE code_hash=? AND node_id=? AND expires>?",
                                      (fingerprint(code), node_id, self.clock())).fetchone()
            if pairing is None:
                # Idempotent response only for the same credential already enrolled.
                node = self.db.execute("SELECT * FROM nodes WHERE id=? AND enabled=1", (node_id,)).fetchone()
                if node and node["credential_hash"] and hmac.compare_digest(node["credential_hash"], fingerprint(credential)):
                    return {"enrolled": True}
                raise ProtocolError("invalid_pairing", 401)
            self.db.execute("UPDATE nodes SET credential_hash=?, enabled=1 WHERE id=?",
                            (fingerprint(credential), node_id))
            self.db.execute("DELETE FROM pairings WHERE node_id=?", (node_id,))
            self.db.execute("DELETE FROM sessions WHERE node_id=?", (node_id,))
            self.event("enrolled", node_id=node_id)
        return {"enrolled": True}

    def session(self, node_id, credential):
        if not isinstance(credential, str) or len(credential) > 128:
            raise ProtocolError("unauthorized", 401)
        with self.transaction():
            row = self.db.execute("SELECT * FROM nodes WHERE id=? AND enabled=1", (node_id,)).fetchone()
            if not row or not row["credential_hash"] or not hmac.compare_digest(row["credential_hash"], fingerprint(credential)):
                raise ProtocolError("unauthorized", 401)
            token = secrets.token_urlsafe(32)
            # Only one active session per node; rotating credentials invalidates previous sessions.
            self.db.execute("DELETE FROM sessions WHERE node_id=?", (node_id,))
            self.db.execute("INSERT INTO sessions VALUES(?,?,?)", (fingerprint(token), node_id, self.clock() + self.session_ttl))
        return {"token": token, "expires_in": self.session_ttl}

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) > 128:
            raise ProtocolError("unauthorized", 401)
        row = self.db.execute("""SELECT s.node_id FROM sessions s JOIN nodes n ON n.id=s.node_id
            WHERE s.token_hash=? AND s.expires>? AND n.enabled=1""", (fingerprint(token), self.clock())).fetchone()
        if row is None:
            raise ProtocolError("unauthorized", 401)
        return row[0]

    def revoke(self, node_id):
        with self.transaction():
            self.db.execute("UPDATE nodes SET enabled=0,credential_hash=NULL WHERE id=?", (node_id,))
            self.db.execute("DELETE FROM sessions WHERE node_id=?", (node_id,))
            self.db.execute("DELETE FROM pairings WHERE node_id=?", (node_id,))
            self.db.execute("UPDATE jobs SET state='queued', result=NULL,result_hash=NULL,lease=NULL WHERE node_id=?", (node_id,))
            self.event("revoked", node_id=node_id)
        return {"revoked": node_id}

    def submit(self, query, channel, limit, request_id):
        if not isinstance(query, str) or not query.strip() or len(query) > 512 or "\x00" in query:
            raise ProtocolError("invalid_query")
        if channel not in {"pwa", "feishu"} or type(limit) is not int or not 1 <= limit <= 100:
            raise ProtocolError("invalid_search_options")
        identifier(request_id)
        with self.transaction():
            old = self.db.execute("SELECT * FROM tasks WHERE request_id=?", (request_id,)).fetchone()
            if old:
                if (old["query"], old["channel"], old["result_limit"]) != (query, channel, limit):
                    raise ProtocolError("idempotency_conflict", 409)
                return {"task_id": old["id"], "created": False}
            task_id = str(uuid.uuid4())
            self.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)",
                            (task_id, request_id, query, channel, limit, self.clock()))
            self.db.execute("INSERT INTO jobs(task_id,node_id) SELECT ?,id FROM nodes WHERE enabled=1", (task_id,))
            if not self.db.execute("SELECT 1 FROM jobs WHERE task_id=?", (task_id,)).fetchone():
                raise ProtocolError("no_nodes", 409)
            self.event("submitted", task_id)
        return {"task_id": task_id, "created": True}

    def poll(self, node_id, policy_hash):
        if not isinstance(policy_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", policy_hash):
            raise ProtocolError("invalid_policy_hash")
        with self.transaction():
            previous = self.db.execute("SELECT policy_hash FROM nodes WHERE id=? AND enabled=1", (node_id,)).fetchone()
            if previous is None:
                raise ProtocolError("unknown_node", 404)
            if previous[0] != policy_hash:
                # Revocations invalidate historical cached metadata and in-flight leases.
                self.db.execute("""UPDATE jobs SET state='queued',result=NULL,result_hash=NULL,
                    lease=NULL,lease_until=NULL,retry_at=0 WHERE node_id=?""", (node_id,))
            self.db.execute("UPDATE nodes SET last_seen=?,policy_hash=? WHERE id=?", (self.clock(), policy_hash, node_id))
            job = self.db.execute("""SELECT j.*,t.query,t.channel,t.result_limit FROM jobs j JOIN tasks t ON t.id=j.task_id
                WHERE j.node_id=? AND j.state!='done' AND j.retry_at<=?
                AND (j.lease IS NULL OR j.lease_until<=?) ORDER BY t.created,t.id LIMIT 1""",
                                  (node_id, self.clock(), self.clock())).fetchone()
            if job is None:
                return {"job": None}
            lease = secrets.token_urlsafe(32)
            self.db.execute("""UPDATE jobs SET state='running',lease=?,lease_until=?,policy_hash=?
                WHERE task_id=? AND node_id=?""", (lease, self.clock() + self.lease_ttl, policy_hash, job["task_id"], node_id))
            self.event("claimed", job["task_id"], node_id)
            return {"job": {"task_id": job["task_id"], "lease": lease, "lease_seconds": self.lease_ttl,
                            "query": job["query"], "channel": job["channel"], "limit": job["result_limit"]}}

    def complete(self, node_id, task_id, lease, result):
        with self.transaction():
            if not self.db.execute("SELECT 1 FROM nodes WHERE id=? AND enabled=1", (node_id,)).fetchone():
                raise ProtocolError("unauthorized", 401)
            job = self.db.execute("""SELECT j.*,t.channel,t.result_limit FROM jobs j JOIN tasks t ON t.id=j.task_id
                WHERE j.task_id=? AND j.node_id=?""", (task_id, node_id)).fetchone()
            if not job or not isinstance(lease, str) or job["lease"] != lease:
                raise ProtocolError("stale_lease", 409)
            serialized = metadata_result(result, node_id, job["channel"])
            if len(result["hits"]) > job["result_limit"]:
                raise ProtocolError("too_many_hits")
            result_hash = fingerprint(serialized)
            if job["result_hash"] is not None and job["state"] in {"done", "waiting_source"}:
                if job["result_hash"] != result_hash:
                    raise ProtocolError("completion_conflict", 409)
                return {"accepted": True, "duplicate": True}
            if job["lease_until"] <= self.clock():
                raise ProtocolError("stale_lease", 409)
            waiting = any(s["status"] == "waiting_for_source" for s in result["sources"])
            self.db.execute("""UPDATE jobs SET state=?,result=?,result_hash=?,retry_at=?
                WHERE task_id=? AND node_id=?""", ("waiting_source" if waiting else "done", serialized, result_hash,
                                                    self.clock() + 60 if waiting else 0, task_id, node_id))
            # Waiting sources are retried without waiting for the expired execution lease.
            if waiting:
                self.db.execute("UPDATE jobs SET lease_until=? WHERE task_id=? AND node_id=?", (self.clock(), task_id, node_id))
            self.event("partial_source" if waiting else "completed", task_id, node_id)
        return {"accepted": True, "duplicate": False}

    def view(self, task_id):
        # Consistent read snapshot while other processes finish jobs.
        self.db.execute("BEGIN")
        try:
            task = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if task is None:
                raise ProtocolError("unknown_task", 404)
            jobs = self.db.execute("""SELECT j.*,n.last_seen,n.enabled FROM jobs j JOIN nodes n ON n.id=j.node_id
                WHERE j.task_id=? ORDER BY j.node_id""", (task_id,)).fetchall()
            hits, nodes, waiting = [], [], []
            for job in jobs:
                online = bool(job["enabled"] and job["last_seen"] is not None
                              and self.clock() - job["last_seen"] < self.offline_after)
                state = ("completed" if job["state"] == "done" else "waiting_for_node" if not online
                         else "waiting_for_source" if job["state"] == "waiting_source"
                         else "running" if job["state"] == "running" and job["lease_until"] > self.clock() else "queued")
                nodes.append({"node_id": job["node_id"], "online": online, "state": state})
                if job["state"] != "done":
                    waiting.append(job["node_id"])
                if job["result"]:
                    hits.extend(json.loads(job["result"])["hits"])
            return {"task_id": task_id, "channel": task["channel"], "state": "waiting" if waiting else "completed",
                    "partial": bool(waiting), "waiting_nodes": waiting, "nodes": nodes,
                    "results": group_replicas(hits), "metadata_only": True}
        finally:
            self.db.execute("ROLLBACK")

    def audit(self):
        return {"events": [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY sequence DESC LIMIT 100")]}

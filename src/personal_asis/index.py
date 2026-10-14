"""Transactional local FTS index. Sources are always opened read-only."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .config import Config
from .markdown import digest, excerpt, parse
from .extractors import extract, ExtractionError, MAX_SOURCE_BYTES, EXTRACTOR_VERSION


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
 id TEXT PRIMARY KEY, root TEXT NOT NULL, policy TEXT NOT NULL,
 enabled INTEGER NOT NULL, remote_metadata INTEGER NOT NULL,
 available INTEGER NOT NULL DEFAULT 0, checked_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
 rowid INTEGER PRIMARY KEY, document_id TEXT UNIQUE NOT NULL,
 source_id TEXT NOT NULL REFERENCES sources(id), path TEXT NOT NULL,
 device INTEGER NOT NULL, inode INTEGER NOT NULL, size INTEGER NOT NULL,
 mtime_ns INTEGER NOT NULL, ctime_ns INTEGER NOT NULL,
 content_hash TEXT NOT NULL, title TEXT NOT NULL, policy TEXT NOT NULL,
 links TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 indexed_at TEXT NOT NULL, index_version INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS current_path ON documents(source_id, path) WHERE active=1;
CREATE TABLE IF NOT EXISTS versions (
 document_id TEXT NOT NULL, content_hash TEXT NOT NULL, indexed_at TEXT NOT NULL,
 index_version INTEGER NOT NULL, path TEXT NOT NULL,
 PRIMARY KEY(document_id, content_hash)
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(title, text, tokenize='trigram');
CREATE TABLE IF NOT EXISTS operations (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, at TEXT NOT NULL, details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS extractions (
 document_id TEXT PRIMARY KEY, format TEXT NOT NULL, locations TEXT NOT NULL,
 extractor_version TEXT NOT NULL, units INTEGER NOT NULL, text_units INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS extraction_failures (
 source_id TEXT NOT NULL, path TEXT NOT NULL, signature TEXT NOT NULL,
 reason TEXT NOT NULL, checked_at TEXT NOT NULL, PRIMARY KEY(source_id,path)
);
PRAGMA user_version=2;
"""


class Index:
    def __init__(self, path: Path, config: Config):
        self.config = config
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in {0, 1, 2}:
            raise ValueError("不支持此数据库版本")
        try:
            if version != 2:
                self.db.executescript(SCHEMA)
        except sqlite3.OperationalError as exc:
            self.db.close()
            if "fts5" in str(exc).lower() or "trigram" in str(exc).lower():
                raise ValueError("需要带 FTS5 trigram 的 SQLite 3.34+；运行 doctor 核查") from exc
            raise
        with self.db:
            self._sync_config()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def _remove(self, row):
        self.db.execute("DELETE FROM search_index WHERE rowid=?", (row["rowid"],))
        self.db.execute("UPDATE documents SET active=0 WHERE rowid=?", (row["rowid"],))

    def _sync_config(self):
        current = {s.id: s for s in self.config.sources}
        stored_sources = {r["id"]: r for r in self.db.execute("SELECT * FROM sources").fetchall()}
        for stored in stored_sources.values():
            source = current.get(stored["id"])
            if source is None or not source.index or str(source.root) != stored["root"]:
                if self.db.execute("SELECT 1 FROM extraction_failures WHERE source_id=? LIMIT 1", (stored["id"],)).fetchone():
                    self.db.execute("DELETE FROM extraction_failures WHERE source_id=?", (stored["id"],))
                for row in self.db.execute("SELECT * FROM documents WHERE source_id=? AND active=1",
                                           (stored["id"],)).fetchall():
                    self._remove(row)
                if stored["enabled"] or stored["available"]:
                    self.db.execute("UPDATE sources SET enabled=0, available=0 WHERE id=?", (stored["id"],))
        for source in current.values():
            stored = stored_sources.get(source.id)
            values = (str(source.root), source.policy, source.index, source.remote_metadata)
            if stored is None or tuple(stored[k] for k in ("root", "policy", "enabled", "remote_metadata")) != values:
                self.db.execute("""INSERT INTO sources(id,root,policy,enabled,remote_metadata)
                    VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET root=excluded.root,
                    policy=excluded.policy,enabled=excluded.enabled,remote_metadata=excluded.remote_metadata""",
                                (source.id, *values))
            for row in self.db.execute("SELECT * FROM documents WHERE source_id=? AND active=1",
                                       (source.id,)).fetchall():
                if source.excludes(row["path"]) or Path(row["path"]).suffix.lower().lstrip(".") not in source.formats:
                    self._remove(row)
            for row in self.db.execute("SELECT path FROM extraction_failures WHERE source_id=?", (source.id,)).fetchall():
                if source.excludes(row["path"]) or Path(row["path"]).suffix.lower().lstrip(".") not in source.formats:
                    self.db.execute("DELETE FROM extraction_failures WHERE source_id=? AND path=?", (source.id, row["path"]))

    def _record(self, kind, details):
        self.db.execute("INSERT INTO operations VALUES(?,?,?,?)",
                        (str(uuid.uuid4()), kind, now(), json.dumps(details, ensure_ascii=False)))
        # Audit does not retain query plaintext or source titles/excerpts.
        cutoff = datetime.fromtimestamp(time.time() - 180 * 86400, timezone.utc).isoformat()
        self.db.execute("DELETE FROM operations WHERE at < ?", (cutoff,))

    @contextmanager
    def _reconcile_lock(self):
        # Serialize scanners without holding SQLite's write lock while doing I/O.
        import fcntl
        with self.path.with_name(self.path.name + ".reconcile.lock").open("a+b") as handle:
            os.chmod(handle.name, 0o600)
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _scan(source):
        if not source.root.is_dir() or source.root.is_symlink():
            raise OSError("source_unavailable")
        found = {}
        def failed(error):
            raise error
        for base, dirs, files in os.walk(source.root, followlinks=False, onerror=failed):
            base = Path(base)
            dirs[:] = sorted(d for d in dirs if not (base / d).is_symlink()
                             and not source.excludes((base / d).relative_to(source.root).as_posix()))
            for name in sorted(files):
                path = base / name
                rel = path.relative_to(source.root).as_posix()
                if path.suffix.lower().lstrip(".") not in source.formats or path.is_symlink() or source.excludes(rel):
                    continue
                stat = path.stat()
                found[rel] = (path, stat)
        return found

    @staticmethod
    def _read(path, expected=None, root=None):
        # Open each descendant relative to directory FDs so an ancestor symlink
        # replacement cannot redirect source reads outside the configured root.
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if root is None:
            fd = os.open(path, os.O_RDONLY | nofollow)
        else:
            parts = path.relative_to(root).parts
            if not parts or any(part in {".", ".."} for part in parts):
                raise OSError("invalid_source_path")
            directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | nofollow)
            try:
                for part in parts[:-1]:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | nofollow, dir_fd=directory)
                    os.close(directory)
                    directory = child
                fd = os.open(parts[-1], os.O_RDONLY | nofollow, dir_fd=directory)
            finally:
                os.close(directory)
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read(MAX_SOURCE_BYTES + 1)
            after = os.fstat(handle.fileno())
        attrs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        stamp = lambda s: tuple(getattr(s, attr) for attr in attrs)
        if stamp(before) != stamp(after) or (expected and stamp(before) != stamp(expected)):
            raise OSError("source_changed_during_read")
        if len(raw) > MAX_SOURCE_BYTES:
            raise ExtractionError("source_too_large")
        return raw, after

    def reconcile(self, force=False, progress=None):
        report = {"node_id": self.config.node_id, "sources": [],
                  "added": 0, "modified": 0, "moved": 0, "deleted": 0, "unchanged": 0,
                  "hashes_computed": 0}
        with self._reconcile_lock():
            with self.db:
                self._sync_config()
                previous = self.db.execute("SELECT value FROM state WHERE key='index_version'").fetchone()
                generation = int(previous[0]) + 1 if previous else 1
                self.db.execute("INSERT OR REPLACE INTO state VALUES('index_version',?)", (str(generation),))
            for source in self.config.sources:
                if not source.index:
                    continue
                try:
                    found = self._scan(source)
                    old = {r["path"]: r for r in self.db.execute(
                        "SELECT * FROM documents WHERE source_id=? AND active=1", (source.id,))}
                    new_inodes = Counter((s.st_dev, s.st_ino) for _, s in found.values())
                    inode_paths = {(s.st_dev, s.st_ino): p for p, (_, s) in found.items()}
                    old_inodes = defaultdict(list)
                    for row in old.values():
                        old_inodes[(row["device"], row["inode"])].append(row)
                    # Read all candidate files before changing this source's index.
                    updates = []
                    failures = []
                    prior_failures = {r["path"]: r for r in self.db.execute(
                        "SELECT * FROM extraction_failures WHERE source_id=?", (source.id,))}
                    unchanged = 0
                    hashes = 0
                    retained = set()
                    for ordinal, (rel, (path, stat)) in enumerate(found.items(), 1):
                        if progress and (ordinal == 1 or ordinal % 25 == 0):
                            progress({"source_id": source.id, "processed": ordinal - 1, "files_seen": len(found)})
                        row = old.get(rel)
                        if (row and (row["device"], row["inode"]) != (stat.st_dev, stat.st_ino)
                                and inode_paths.get((row["device"], row["inode"]), rel) != rel):
                            # The old file moved elsewhere; a replacement at its previous
                            # path must not consume the moved file's document identity.
                            row = None
                        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                        failed = prior_failures.get(rel)
                        if not force and failed and failed["signature"] == json.dumps(signature):
                            failures.append((rel, json.dumps(signature), failed["reason"]))
                            continue
                        if row and not force and signature == tuple(row[k] for k in
                              ("device", "inode", "size", "mtime_ns", "ctime_ns")):
                            unchanged += 1
                            retained.add(row["rowid"])
                            continue
                        try:
                            if stat.st_size > MAX_SOURCE_BYTES:
                                raise ExtractionError("source_too_large")
                            raw, stat = self._read(path, stat, source.root)
                            extraction = extract(raw, path)
                            text = extraction["text"]
                        except ExtractionError as exc:
                            failures.append((rel, json.dumps(signature), exc.reason))
                            continue
                        content_hash = digest(raw)
                        hashes += 1
                        moved = False
                        inode = (stat.st_dev, stat.st_ino)
                        candidates = old_inodes[inode]
                        # No content-only move guessing; copies keep separate UUIDs.
                        if (len(candidates) == 1 and new_inodes[inode] == 1
                                and candidates[0]["content_hash"] == content_hash
                                and candidates[0]["path"] != rel):
                            row = candidates[0]
                            moved = True
                        if row:
                            if row["rowid"] in retained:
                                # Ambiguous replacement: assign a new identity rather than reuse twice.
                                row = None
                                moved = False
                            else:
                                retained.add(row["rowid"])
                        updates.append((rel, stat, row, moved, text, content_hash, extraction["metadata"], extraction))
                except (OSError, UnicodeError):
                    with self.db:
                        self.db.execute("UPDATE sources SET available=0,checked_at=? WHERE id=?", (now(), source.id))
                    report["sources"].append({"source_id": source.id, "status": "unavailable_or_unreadable"})
                    continue
                with self.db:
                    for row in old.values():
                        if row["rowid"] not in retained:
                            self._remove(row)
                            report["deleted"] += 1
                    # Release unique current paths before applying moves, including path swaps.
                    self.db.execute("DELETE FROM extraction_failures WHERE source_id=?", (source.id,))
                    self.db.executemany("INSERT INTO extraction_failures VALUES(?,?,?,?,?)",
                                        [(source.id, rel, signature, reason, now()) for rel, signature, reason in failures])
                    for _, _, row, _, _, _, _, _ in updates:
                        if row:
                            self.db.execute("UPDATE documents SET active=0 WHERE rowid=?", (row["rowid"],))
                    for rel, stat, row, moved, text, content_hash, metadata, extraction in updates:
                        doc_id = row["document_id"] if row else str(uuid.uuid4())
                        policy = "private" if source.policy == "private" or source.is_private_path(rel) or metadata["private"] else "normal"
                        indexed_at = now()
                        fields = (doc_id, source.id, rel, stat.st_dev, stat.st_ino, stat.st_size,
                                  stat.st_mtime_ns, stat.st_ctime_ns, content_hash, metadata["title"],
                                  policy, json.dumps(metadata["links"], ensure_ascii=False), indexed_at, generation)
                        if row:
                            self.db.execute("""UPDATE documents SET document_id=?,source_id=?,path=?,device=?,inode=?,
                              size=?,mtime_ns=?,ctime_ns=?,content_hash=?,title=?,policy=?,links=?,indexed_at=?,
                              index_version=?,active=1 WHERE rowid=?""", (*fields, row["rowid"]))
                            rowid = row["rowid"]
                            self.db.execute("DELETE FROM search_index WHERE rowid=?", (rowid,))
                        else:
                            rowid = self.db.execute("""INSERT INTO documents(document_id,source_id,path,device,inode,
                              size,mtime_ns,ctime_ns,content_hash,title,policy,links,indexed_at,index_version)
                              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", fields).lastrowid
                        self.db.execute("INSERT INTO search_index(rowid,title,text) VALUES(?,?,?)",
                                        (rowid, metadata["title"], text))
                        self.db.execute("INSERT OR REPLACE INTO extractions VALUES(?,?,?,?,?,?)",
                            (doc_id, extraction["format"], json.dumps(extraction["locations"], ensure_ascii=False),
                             EXTRACTOR_VERSION, extraction["units"], extraction["text_units"]))
                        self.db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?)",
                                        (doc_id, content_hash, indexed_at, generation, rel))
                        report["moved" if moved else "modified" if row else "added"] += 1
                    report["unchanged"] += unchanged
                    report["hashes_computed"] += hashes
                    self.db.execute("UPDATE sources SET available=1,checked_at=? WHERE id=?", (now(), source.id))
                    report["sources"].append({"source_id": source.id, "status": "ready",
                        "documents": len(found) - len(failures), "files_seen": len(found),
                        "skipped_documents": len(failures), "skipped_reasons": dict(Counter(f[2] for f in failures))})
            with self.db:
                self._record("reconcile", report)
        report["index_version"] = generation
        return report

    def _current(self, row):
        source = next((s for s in self.config.sources if s.id == row["source_id"]), None)
        if (not source or not source.index or source.excludes(row["path"])
                or Path(row["path"]).suffix.lower().lstrip(".") not in source.formats):
            return None
        path = source.root / row["path"]
        try:
            # Ancestor symlinks are also disallowed, including replacements after reconciliation.
            if source.root.is_symlink() or not path.resolve().is_relative_to(source.root.resolve()):
                return None
            if any(p.is_symlink() for p in [path, *list(path.parents)[:len(Path(row["path"]).parts) - 1]]):
                return None
            raw, _ = self._read(path, root=source.root)
            if digest(raw) != row["content_hash"]:
                return None
            if path.suffix.lower() == ".md":
                text = raw.decode("utf-8-sig")
                marked_private = parse(text, path.stem)["private"]
            else:
                stored = self.db.execute("SELECT text FROM search_index WHERE rowid=?", (row["rowid"],)).fetchone()
                extraction = self.db.execute("SELECT * FROM extractions WHERE document_id=?", (row["document_id"],)).fetchone()
                if stored is None or extraction is None:
                    return None
                text, marked_private = stored[0], False
            private = source.policy == "private" or source.is_private_path(row["path"]) or marked_private
            return source, path, text, private
        except (OSError, UnicodeError, ExtractionError):
            return None

    def search(self, query, channel="local", limit=20):
        if channel not in {"local", "pwa", "feishu"}:
            raise ValueError("不支持的渠道")
        if not 1 <= limit <= 100:
            raise ValueError("limit 必须在 1..100")
        terms = re.findall(r"\S+", query.strip())
        if not terms or len(query) > 512:
            raise ValueError("搜索词不能为空且不能超过 512 字符")
        long = [term for term in terms if len(term) >= 3]
        short = [term for term in terms if len(term) < 3]
        conditions = ["d.active=1", "s.enabled=1", "s.available=1"]
        params = []
        if long:
            conditions.append("search_index MATCH ?")
            params.append(" AND ".join('"' + term.replace('"', '""') + '"' for term in long))
        for term in short:
            conditions.append("instr(lower(search_index.title || char(10) || search_index.text),lower(?)) > 0")
            params.append(term)
        rank = "bm25(search_index, 3.0, 1.0)" if long else "0"
        sql = f"""SELECT d.*, {rank} AS rank FROM search_index
          JOIN documents d ON d.rowid=search_index.rowid JOIN sources s ON s.id=d.source_id
          WHERE {' AND '.join(conditions)} ORDER BY rank, d.document_id"""
        hits = []
        stale = 0
        # Release the FTS read snapshot before verifying files and writing audit.
        # A concurrent daemon commit otherwise makes SQLite's read-to-write
        # upgrade fail with SQLITE_BUSY_SNAPSHOT, regardless of busy_timeout.
        candidates = self.db.execute(sql, params).fetchall()
        for row in candidates:
            source = next(s for s in self.config.sources if s.id == row["source_id"])
            if channel != "local" and not source.shares_metadata(False, row["path"]):
                continue
            current = self._current(row)
            if current is None:
                stale += 1
                continue
            source, path, text, private = current
            if channel != "local" and not source.shares_metadata(private, row["path"]):
                continue
            hit = {"document_id": row["document_id"], "content_hash": row["content_hash"],
                   "title": row["title"], "node_id": self.config.node_id, "source_id": source.id,
                   "path_hint": row["path"], "indexed_at": row["indexed_at"],
                   "index_version": row["index_version"]}
            if channel == "local":
                location = excerpt(text, terms)
                hit.update(location)
                hit["original_uri"] = path.as_uri()
                hit["policy"] = "private" if private else "normal"
                hit["read_at"] = now()
                extraction = self.db.execute("SELECT * FROM extractions WHERE document_id=?", (row["document_id"],)).fetchone()
                if extraction and extraction["format"] != "md":
                    hit["format"] = extraction["format"]
                    hit["location"] = next(({k:v for k,v in unit.items() if k not in {"line_start", "line_end"}}
                        for unit in json.loads(extraction["locations"])
                        if unit["line_start"] <= location["line_start"] <= unit["line_end"]), {})
            elif source.remote_evidence and not private:
                hit["reader_allowed"] = True
            # PA0 remote payloads are metadata only; private evidence transport is deferred.
            hits.append(hit)
            if len(hits) >= limit:
                break
        status = self.status()
        result = {"node_id": self.config.node_id, "scope": "local_node",
                  "channel": channel, "results": group_replicas(hits),
                  "sources": status["sources"], "stale_candidates_skipped": stale}
        with self.db:
            self._record("search", {"query_hash": digest(query.encode()), "channel": channel,
                                    "hits": len(hits), "stale_candidates_skipped": stale})
        return result

    def catalog(self):
        result = []
        for row in self.db.execute("""SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id
                                  WHERE d.active=1 AND s.enabled=1 AND s.available=1"""):
            source = next(s for s in self.config.sources if s.id == row["source_id"])
            if not source.shares_metadata(False, row["path"]):
                continue
            current = self._current(row)
            if current:
                source, _, _, private = current
                if source.shares_metadata(private, row["path"]):
                    result.append({"node_id": self.config.node_id, "source_id": source.id,
                                   "document_id": row["document_id"], "content_hash": row["content_hash"],
                                   "title": row["title"], "path_hint": row["path"],
                                   "indexed_at": row["indexed_at"], "available": True})
        return {"node_id": self.config.node_id, "documents": result}

    def reader(self, job):
        row = self.db.execute("SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.document_id=? AND d.active=1 AND s.enabled=1 AND s.available=1", (job["document_id"],)).fetchone()
        if row is None:
            return {"status": "missing"}
        if row["content_hash"] != job["content_hash"]:
            return {"status": "stale"}
        current = self._current(row)
        if current is None:
            return {"status": "stale"}
        source, path, text, private = current
        if private or not source.remote_evidence or not source.shares_metadata(False, row["path"]):
            return {"status": "denied"}
        extraction = self.db.execute("SELECT * FROM extractions WHERE document_id=?", (row["document_id"],)).fetchone()
        fmt = path.suffix.lower().lstrip(".")
        if job["mode"] == "excerpt":
            selection = excerpt(text, job["query"].split())
            selected_text = selection["excerpt"]
            line, cursor, following = selection["line_start"], None, None
        else:
            cursor = job["cursor"]
            if cursor > len(text):
                return {"status": "stale"}
            selected_text = text[cursor:cursor + 6000]
            following = cursor + len(selected_text) if cursor + len(selected_text) < len(text) else None
            line = text.count("\n", 0, cursor) + 1
        locator = {"kind": "line", "line": line}
        if extraction and extraction["format"] != "md":
            locator = next(({k:v for k,v in unit.items() if k not in {"line_start", "line_end"}}
                for unit in json.loads(extraction["locations"])
                if unit["line_start"] <= line <= unit["line_end"]), locator)
        self._record("reader", {"channel": "pwa", "mode": job["mode"], "characters": len(selected_text)})
        self.db.commit()
        return {"status": "ready", "value": {"text": selected_text, "locator": locator, "format": fmt,
                "cursor": cursor, "next_cursor": following, "total_characters": len(text), "mode": job["mode"]}}

    def status(self):
        sources = []
        for source in self.config.sources:
            row = self.db.execute("SELECT * FROM sources WHERE id=?", (source.id,)).fetchone()
            count = self.db.execute("SELECT count(*) FROM documents WHERE source_id=? AND active=1", (source.id,)).fetchone()[0]
            sources.append({"source_id": source.id, "status": "disabled" if not source.index
                            else "ready" if row["available"] and source.root.is_dir() and not source.root.is_symlink()
                            else "waiting_for_source",
                            "documents": count, "checked_at": row["checked_at"],
                            "skipped_documents": self.db.execute("SELECT count(*) FROM extraction_failures WHERE source_id=?", (source.id,)).fetchone()[0],
                            "skipped_reasons": {r["reason"]:r["n"] for r in self.db.execute(
                                "SELECT reason,count(*) n FROM extraction_failures WHERE source_id=? GROUP BY reason", (source.id,))}})
        return {"node_id": self.config.node_id, "sources": sources}


def group_replicas(hits):
    groups = {}
    for hit in hits:
        groups.setdefault(hit["content_hash"], {"content_hash": hit["content_hash"], "replicas": []})["replicas"].append(hit)
    return list(groups.values())

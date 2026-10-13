"""PA0's Feishu boundary, independent of AstrBot's model and conversation state."""

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

from .coordinator import Coordinator, ProtocolError


def summary(view, pwa_origin=None):
    """Render a fixed whitelist, even if a future evidence result contains text."""
    lines = [f"PA0 搜索 {view['task_id']}", "部分结果，等待补全" if view["partial"] else "搜索完成"]
    if view["waiting_nodes"]:
        lines.append("等待节点：" + "、".join(view["waiting_nodes"]))
    for node in view["nodes"]:
        state = {"completed": "已搜索", "waiting_for_node": "离线等待", "queued": "排队",
                 "running": "检索中", "waiting_for_source": "来源暂不可用"}.get(node["state"], "状态待核")
        lines.append(f"{node['node_id']}：{state}")
    replicas = [r for g in view["results"] for r in g["replicas"]]
    if not replicas:
        lines.append("目前没有获准远程显示的命中；仅搜索已在本机授权的来源。")
    for hit in replicas[:20]:
        lines.append(f"• {hit['title'][:160]}｜{hit['node_id']}/{hit['source_id']}｜{hit['path_hint'][:240]}")
    if len(replicas) > 20:
        lines.append(f"另有 {len(replicas) - 20} 个副本；使用本机 CLI 查看。")
    lines.append("此处仅显示元数据，不含正文或摘录。")
    if pwa_origin:
        lines.append(f"控制台：{pwa_origin}/#task={view['task_id']}")
    return "\n".join(lines)


def view_digest(view):
    # Ignore routine heartbeat/online changes and queued -> running transitions:
    # notify on initial receipt, actual results, source waiting and completion.
    value = {key: view[key] for key in ("task_id", "partial", "waiting_nodes", "results")}
    value["waiting_sources"] = [n["node_id"] for n in view["nodes"] if n["state"] == "waiting_for_source"]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


class FeishuBridge:
    def __init__(self, home, clock=time.time):
        self.home, self.clock = Path(home), clock
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.home / "feishu.sqlite3"
        self.db = sqlite3.connect(path, timeout=30)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS binding (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                platform_id TEXT, open_id TEXT, code_hash TEXT, expires REAL
            );
            INSERT OR IGNORE INTO binding(singleton) VALUES(1);
            CREATE TABLE IF NOT EXISTS routes (
                task_id TEXT PRIMARY KEY, platform_id TEXT NOT NULL,
                open_id TEXT NOT NULL, message_id TEXT NOT NULL,
                last_digest TEXT, created REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS deliveries (
                id TEXT PRIMARY KEY, task_id TEXT, state TEXT NOT NULL,
                created REAL NOT NULL, updated REAL NOT NULL
            );
        """)
        cutoff = self.clock() - 180 * 86400
        with self.db:
            self.db.execute("DELETE FROM routes WHERE created < ?", (cutoff,))
            self.db.execute("DELETE FROM deliveries WHERE created < ?", (cutoff,))

    def close(self):
        self.db.close()

    def pairing(self, platform_id):
        code = secrets.token_urlsafe(24)
        with self.db:
            self.db.execute("UPDATE binding SET platform_id=?,code_hash=?,expires=? WHERE singleton=1",
                            (platform_id, hashlib.sha256(code.encode()).hexdigest(), self.clock() + 600))
        return {"pairing_code": code, "expires_in": 600}

    def bind(self, platform_id, open_id, code):
        if not isinstance(open_id, str) or not re.fullmatch(r"ou_[A-Za-z0-9_-]{1,128}", open_id):
            return False
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT * FROM binding WHERE singleton=1").fetchone()
            if (row["platform_id"] != platform_id or row["code_hash"] is None
                    or row["expires"] <= self.clock() or not isinstance(code, str) or len(code) > 128
                    or not hmac.compare_digest(row["code_hash"], hashlib.sha256(code.encode()).hexdigest())):
                self.db.rollback()
                return False
            self.db.execute("UPDATE binding SET open_id=?,code_hash=NULL,expires=NULL WHERE singleton=1", (open_id,))
            # Rebinding cannot send old notifications to a newly selected owner.
            self.db.execute("DELETE FROM routes WHERE open_id!=? OR platform_id!=?", (open_id, platform_id))
            self.db.commit()
            return True
        except BaseException:
            self.db.rollback()
            raise

    def authorized(self, platform_id, open_id):
        row = self.db.execute("SELECT * FROM binding WHERE singleton=1").fetchone()
        return bool(row["open_id"] and row["platform_id"] == platform_id and row["open_id"] == open_id)

    def submit(self, platform_id, open_id, message_id, query):
        if not self.authorized(platform_id, open_id):
            raise ProtocolError("unauthorized", 403)
        request_id = hashlib.sha256(f"{platform_id}\0{message_id}".encode()).hexdigest()
        with Coordinator(self.home / "coordinator.sqlite3", nodes=("mac",)) as c:
            task = c.submit(query, "feishu", 20, request_id)["task_id"]
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO routes VALUES(?,?,?,?,NULL,?)",
                            (task, platform_id, open_id, message_id, self.clock()))
        return task

    def view(self, platform_id, open_id, task_id):
        if not self.authorized(platform_id, open_id):
            raise ProtocolError("unauthorized", 403)
        route = self.db.execute("SELECT * FROM routes WHERE task_id=? AND platform_id=? AND open_id=?",
                                (task_id, platform_id, open_id)).fetchone()
        if not route:
            raise ProtocolError("unknown_task", 404)
        with Coordinator(self.home / "coordinator.sqlite3", nodes=("mac",)) as c:
            return c.view(task_id)

    def pending(self):
        output = []
        for row in self.db.execute("SELECT * FROM routes ORDER BY created").fetchall():
            if not self.authorized(row["platform_id"], row["open_id"]):
                continue
            view = self.view(row["platform_id"], row["open_id"], row["task_id"])
            digest = view_digest(view)
            key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"asis:{row['task_id']}:{row['message_id']}:{digest}"))
            recorded = self.db.execute("SELECT 1 FROM deliveries WHERE id=?", (key,)).fetchone()
            if row["last_digest"] != digest and not recorded:
                output.append((dict(row), view, digest))
        return output

    async def deliver(self, route, view, digest, send):
        if not self.authorized(route["platform_id"], route["open_id"]):
            return "unauthorized"
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"asis:{route['task_id']}:{route['message_id']}:{digest}"))
        # Persist before calling the platform. A crash/timeout is outcome-unknown,
        # so neither restart nor an overlapping worker repeats the external write.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute("SELECT state FROM deliveries WHERE id=?", (key,)).fetchone()
            if previous:
                self.db.rollback()
                return previous[0]
            self.db.execute("INSERT INTO deliveries VALUES(?,?,'sending',?,?)",
                            (key, route["task_id"], self.clock(), self.clock()))
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        try:
            origin = None
            if (self.home / "pwa.json").exists():
                from .pwa import settings
                origin = settings(self.home)["origin"]
            accepted = await send(route["platform_id"], route["message_id"], summary(view, origin), key)
        except Exception:
            with self.db:
                self.db.execute("UPDATE deliveries SET state='unknown',updated=? WHERE id=?", (self.clock(), key))
            return "unknown"
        state = "sent" if accepted else "failed"
        with self.db:
            self.db.execute("UPDATE deliveries SET state=?,updated=? WHERE id=?", (state, self.clock(), key))
            if accepted:
                self.db.execute("UPDATE routes SET last_digest=? WHERE task_id=?", (digest, route["task_id"]))
        return state

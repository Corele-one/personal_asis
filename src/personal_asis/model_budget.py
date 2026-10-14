"""Transactional per-node token reservations; unknown calls are never retried."""

from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo


class ModelBudget:
    def __init__(self, path, node_id, daily=100000, monthly=1000000,
                 timezone="Asia/Shanghai", clock=time.time):
        if type(daily) is not int or type(monthly) is not int or not 0 < daily <= monthly:
            raise ValueError("invalid_model_budget")
        self.node, self.daily, self.monthly = node_id, daily, monthly
        self.zone, self.clock = ZoneInfo(timezone), clock
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=30, isolation_level=None)
        os.chmod(path,0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS model_calls (
            node TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
            day TEXT NOT NULL, month TEXT NOT NULL, state TEXT NOT NULL,
            tokens INTEGER NOT NULL, response TEXT, at REAL NOT NULL,
            PRIMARY KEY(node,request_id))""")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def periods(self):
        local = datetime.fromtimestamp(self.clock(),self.zone)
        return local.strftime("%Y-%m-%d"),local.strftime("%Y-%m")

    def status(self):
        day,month = self.periods()
        used = self.db.execute("""SELECT
            COALESCE(SUM(CASE WHEN day=? THEN tokens ELSE 0 END),0),
            COALESCE(SUM(CASE WHEN month=? THEN tokens ELSE 0 END),0)
            FROM model_calls WHERE node=?""",(day,month,self.node)).fetchone()
        unresolved = self.db.execute("SELECT count(*) FROM model_calls WHERE node=? AND state IN ('reserved','unknown')",(self.node,)).fetchone()[0]
        return {"day":day,"month":month,"daily_tokens":used[0],"monthly_tokens":used[1],
                "daily_limit":self.daily,"monthly_limit":self.monthly,
                "daily_remaining":max(0,self.daily-used[0]),"monthly_remaining":max(0,self.monthly-used[1]),
                "approaching_limit":used[0]>=self.daily*0.8 or used[1]>=self.monthly*0.8,
                "unresolved_calls":unresolved,"includes_reservations":True}

    def reserve(self, request_id, fingerprint, tokens):
        if not isinstance(request_id,str) or not 1 <= len(request_id) <= 128 or type(tokens) is not int or tokens <= 0:
            raise ValueError("invalid_model_request")
        with self.transaction():
            old = self.db.execute("SELECT * FROM model_calls WHERE node=? AND request_id=?",(self.node,request_id)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise ValueError("model_request_id_conflict")
                if old['state'] == 'succeeded':
                    return {"cached":json.loads(old['response'])}
                raise ValueError("model_request_not_retryable_"+old['state'])
            status = self.status()
            if status['daily_tokens']+tokens > self.daily or status['monthly_tokens']+tokens > self.monthly:
                raise ValueError("model_budget_exhausted")
            self.db.execute("INSERT INTO model_calls VALUES(?,?,?,?,?,'reserved',?,NULL,?)",
                            (self.node,request_id,fingerprint,status['day'],status['month'],tokens,self.clock()))
        return {"reserved_tokens":tokens}

    def finish(self, request_id, state, tokens=None, response=None):
        if state not in {'succeeded','unknown','rejected','invalid_output'}:
            raise ValueError("invalid_model_call_state")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("invalid_model_usage")
        with self.transaction():
            row = self.db.execute("SELECT state FROM model_calls WHERE node=? AND request_id=?",(self.node,request_id)).fetchone()
            if row is None or row[0] != 'reserved':
                raise ValueError("model_call_already_settled")
            self.db.execute("""UPDATE model_calls SET state=?,tokens=COALESCE(?,tokens),response=?
                WHERE node=? AND request_id=?""",(state,tokens,
                json.dumps(response,ensure_ascii=False) if response is not None else None,self.node,request_id))

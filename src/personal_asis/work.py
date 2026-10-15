"""Local delegation authority. No scheduler, source grants or external writes.

Workers hold expiring, fenced claims. An interrupted execution is unknown,
never implicitly retried; recovering a claim does not erase that marker.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid


ROLES = ('supervisor', 'research', 'career', 'life')
TERMINAL = ('completed', 'stopped', 'cancelled')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class WorkStore:
    def __init__(self, path, clock=time.time):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.clock = clock
        self.db = sqlite3.connect(path, isolation_level=None, timeout=30)
        os.chmod(path, 0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS delegations (
            id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, fingerprint TEXT NOT NULL,
            node TEXT NOT NULL, goal TEXT NOT NULL, scope TEXT NOT NULL,
            state TEXT NOT NULL, created REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, delegation TEXT NOT NULL REFERENCES delegations(id),
            request_id TEXT NOT NULL, role TEXT NOT NULL, parent TEXT REFERENCES runs(id),
            session TEXT UNIQUE NOT NULL, priority TEXT NOT NULL, state TEXT NOT NULL,
            epoch INTEGER NOT NULL DEFAULT 0, lease REAL NOT NULL DEFAULT 0,
            checkpoint TEXT, result TEXT, payload_at REAL, created REAL NOT NULL,
            UNIQUE(delegation,request_id));
          CREATE TABLE IF NOT EXISTS executions (
            run TEXT NOT NULL REFERENCES runs(id), key TEXT NOT NULL, fingerprint TEXT NOT NULL,
            kind TEXT NOT NULL, state TEXT NOT NULL, resource TEXT, at REAL NOT NULL,
            PRIMARY KEY(run,key));
          CREATE UNIQUE INDEX IF NOT EXISTS execution_resource ON executions(resource)
            WHERE resource IS NOT NULL AND state IN ('started','unknown');
          CREATE TABLE IF NOT EXISTS work_events (
            id INTEGER PRIMARY KEY, delegation TEXT NOT NULL, run TEXT,
            event TEXT NOT NULL, at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS agent_sessions (
            run TEXT PRIMARY KEY REFERENCES runs(id), contract TEXT NOT NULL,
            payload TEXT, at REAL NOT NULL);
        ''')
        self.clean()

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def _event(self, delegation, event, run=None):
        self.db.execute('INSERT INTO work_events(delegation,run,event,at) VALUES(?,?,?,?)',
                        (delegation, run, event, self.clock()))

    def _delegation(self, did):
        row = self.db.execute('SELECT * FROM delegations WHERE id=?', (did,)).fetchone()
        if row is None:
            raise ValueError('delegation_not_found')
        return row

    def _run(self, rid):
        row = self.db.execute('SELECT * FROM runs WHERE id=?', (rid,)).fetchone()
        if row is None:
            raise ValueError('run_not_found')
        return row

    def create(self, request_id, node, goal, sources):
        # Owner-only control plane; sources restrict work, they never grant access.
        if not all(isinstance(v, str) and 0 < len(v) <= limit
                   for v, limit in ((request_id, 128), (node, 128), (goal, 4000))):
            raise ValueError('invalid_delegation')
        if not isinstance(sources, list) or not sources or any(
                not isinstance(s, str) or not 0 < len(s) <= 128 for s in sources):
            raise ValueError('explicit_work_sources_required')
        scope = {'sources': sorted(set(sources))}
        fp = fingerprint([node, goal, scope])
        with self.transaction():
            old = self.db.execute('SELECT * FROM delegations WHERE request_id=?', (request_id,)).fetchone()
            if old:
                if old['fingerprint'] != fp:
                    raise ValueError('delegation_request_conflict')
                return old['id']
            did = str(uuid.uuid4())
            self.db.execute('INSERT INTO delegations VALUES(?,?,?,?,?,?,?,?)',
                            (did, request_id, fp, node, goal, encoded(scope), 'active', self.clock()))
            self._event(did, 'created')
            return did

    def enqueue(self, did, request_id, role='supervisor', parent=None, priority='foreground'):
        if (role not in ROLES or priority not in ('foreground', 'background') or
                not isinstance(request_id, str) or not 0 < len(request_id) <= 128):
            raise ValueError('invalid_run')
        with self.transaction():
            delegation = self._delegation(did)
            old = self.db.execute('SELECT * FROM runs WHERE delegation=? AND request_id=?',
                                  (did, request_id)).fetchone()
            if old:
                if (old['role'], old['parent'], old['priority']) != (role, parent, priority):
                    raise ValueError('run_request_conflict')
                return old['id']
            if delegation['state'] != 'active':
                raise ValueError('delegation_not_active')
            if role != 'supervisor':
                if parent is None:
                    raise ValueError('specialist_requires_supervisor')
                supervisor = self._run(parent)
                if (supervisor['delegation'] != did or supervisor['role'] != 'supervisor' or
                        supervisor['state'] in TERMINAL):
                    raise ValueError('specialist_requires_active_supervisor')
            elif parent is not None:
                raise ValueError('supervisor_cannot_be_specialist_child')
            rid = str(uuid.uuid4())
            self.db.execute('''INSERT INTO runs(id,delegation,request_id,role,parent,session,
                priority,state,created) VALUES(?,?,?,?,?,?,?,'queued',?)''',
                (rid, did, request_id, role, parent, str(uuid.uuid4()), priority, self.clock()))
            self._event(did, 'queued', rid)
            return rid

    def control(self, did, action):
        if action not in ('pause', 'resume', 'cancel'):
            raise ValueError('invalid_delegation_control')
        with self.transaction():
            delegation = self._delegation(did)
            if delegation['state'] == 'cancelled':
                if action == 'cancel':
                    return
                raise ValueError('cancelled_delegation_cannot_resume')
            state = {'pause': 'paused', 'resume': 'active', 'cancel': 'cancelled'}[action]
            self.db.execute('UPDATE delegations SET state=? WHERE id=?', (state, did))
            if action == 'resume':
                self.db.execute("UPDATE runs SET state='queued' WHERE delegation=? AND state='paused'", (did,))
            else:
                # Calls already in flight retain an unknown marker and account lock.
                self.db.execute("""UPDATE executions SET state='unknown' WHERE state='started'
                    AND run IN (SELECT id FROM runs WHERE delegation=?)""", (did,))
                self.db.execute("""UPDATE runs SET state=?,epoch=epoch+1,lease=0
                    WHERE delegation=? AND state NOT IN ('completed','stopped','cancelled')""", (state, did))
            self._event(did, action)

    def stop_run(self, rid):
        with self.transaction():
            row = self._run(rid)
            # Stop descendants too; another future run of the delegation is allowed.
            rows = self.db.execute('''WITH RECURSIVE children(id) AS (
                SELECT ? UNION ALL SELECT runs.id FROM runs JOIN children ON runs.parent=children.id)
                SELECT id FROM children''', (rid,)).fetchall()
            for child in rows:
                self.db.execute("UPDATE executions SET state='unknown' WHERE run=? AND state='started'", (child['id'],))
                self.db.execute("""UPDATE runs SET state='stopped',epoch=epoch+1,lease=0
                    WHERE id=? AND state NOT IN ('completed','stopped','cancelled')""", (child['id'],))
            self._event(row['delegation'], 'stop_run', rid)

    def recover(self, node):
        """Only expired claims; an old worker cannot subsequently commit a result."""
        with self.transaction():
            rows = self.db.execute('''SELECT r.* FROM runs r JOIN delegations d ON d.id=r.delegation
                WHERE d.node=? AND r.state='running' AND r.lease<=?''', (node, self.clock())).fetchall()
            for row in rows:
                self.db.execute("UPDATE executions SET state='unknown' WHERE run=? AND state='started'", (row['id'],))
                self.db.execute("UPDATE runs SET state='waiting_node',epoch=epoch+1,lease=0 WHERE id=?", (row['id'],))
                self._event(row['delegation'], 'lease_expired', row['id'])
            return len(rows)

    def claim(self, node, *, capacity, foreground_reserve, lease_seconds=60, run_id=None):
        if (type(capacity) is not int or type(foreground_reserve) is not int or
                not 0 <= foreground_reserve < capacity or not 1 <= lease_seconds <= 3600):
            raise ValueError('invalid_worker_limits')
        self.recover(node)
        with self.transaction():
            busy = self.db.execute("SELECT count(*) FROM runs WHERE state='running'").fetchone()[0]
            if busy >= capacity:
                return None
            rows = self.db.execute('''SELECT r.* FROM runs r JOIN delegations d ON d.id=r.delegation
                WHERE d.node=? AND d.state='active' AND r.state IN ('queued','waiting_node')
                AND (? IS NULL OR r.id=?)
                ORDER BY CASE r.priority WHEN 'foreground' THEN 0 ELSE 1 END,r.created,r.rowid''', (node,run_id,run_id)).fetchall()
            for row in rows:
                if row['priority'] == 'background' and busy >= capacity - foreground_reserve:
                    continue
                # Unknown executions require inspection; a new epoch is not a retry key.
                if self.db.execute("SELECT 1 FROM executions WHERE run=? AND state='unknown'", (row['id'],)).fetchone():
                    continue
                self.db.execute("UPDATE runs SET state='running',epoch=epoch+1,lease=? WHERE id=?",
                                (self.clock() + lease_seconds, row['id']))
                self._event(row['delegation'], 'claimed', row['id'])
                return dict(self._run(row['id']))
            return None

    def _check(self, rid, node, epoch):
        row = self._run(rid)
        delegation = self._delegation(row['delegation'])
        if (delegation['node'] != node or delegation['state'] != 'active' or
                row['state'] != 'running' or row['epoch'] != epoch or row['lease'] <= self.clock()):
            raise ValueError('inactive_or_stale_work_claim')
        return row

    def heartbeat(self, rid, node, epoch, lease_seconds=60):
        if not 1 <= lease_seconds <= 3600:
            raise ValueError('invalid_lease')
        with self.transaction():
            self._check(rid, node, epoch)
            self.db.execute('UPDATE runs SET lease=? WHERE id=?', (self.clock()+lease_seconds, rid))

    def progress(self, rid, node, epoch, checkpoint, completed=False):
        if len(encoded(checkpoint)) > 32000:
            raise ValueError('work_progress_too_large')
        with self.transaction():
            row = self._check(rid, node, epoch)
            if self.db.execute("SELECT 1 FROM executions WHERE run=? AND state IN ('started','unknown')", (rid,)).fetchone():
                raise ValueError('work_has_unresolved_execution')
            if completed and self.db.execute("""SELECT 1 FROM runs WHERE parent=?
                    AND state NOT IN ('completed','stopped','cancelled')""", (rid,)).fetchone():
                raise ValueError('work_children_not_finished')
            self.db.execute('UPDATE runs SET checkpoint=?,result=?,payload_at=?,state=? WHERE id=?',
                            (encoded(checkpoint), encoded(checkpoint) if completed else None,
                             self.clock(), 'completed' if completed else 'running', rid))
            self._event(row['delegation'], 'completed' if completed else 'progress', rid)

    def begin_execution(self, rid, node, epoch, key, kind, arguments, resource=None):
        if (kind not in ('model', 'tool') or not isinstance(key, str) or not 0 < len(key) <= 128 or
                resource is not None and (not isinstance(resource, str) or not 0 < len(resource) <= 128)):
            raise ValueError('invalid_work_execution')
        fp = fingerprint([kind, arguments, resource])
        with self.transaction():
            self._check(rid, node, epoch)
            old = self.db.execute('SELECT * FROM executions WHERE run=? AND key=?', (rid, key)).fetchone()
            if old:
                if old['fingerprint'] != fp:
                    raise ValueError('execution_key_conflict')
                raise ValueError('execution_not_retryable_' + old['state'])
            try:
                self.db.execute("INSERT INTO executions VALUES(?,?,?,?,'started',?,?)",
                                (rid, key, fp, kind, resource, self.clock()))
            except sqlite3.IntegrityError:
                raise ValueError('account_resource_busy') from None

    def finish_execution(self, rid, node, epoch, key, state):
        if state not in ('done', 'unknown', 'rejected'):
            raise ValueError('invalid_execution_result')
        with self.transaction():
            self._check(rid, node, epoch)
            changed = self.db.execute("UPDATE executions SET state=? WHERE run=? AND key=? AND state='started'",
                                      (state, rid, key)).rowcount
            if not changed:
                raise ValueError('execution_already_settled')

    def view(self, did):
        self.clean()
        row = dict(self._delegation(did))
        row['scope'] = json.loads(row['scope'])
        row.pop('fingerprint')
        row['runs'] = []
        for run in self.db.execute('SELECT * FROM runs WHERE delegation=? ORDER BY created,rowid', (did,)):
            item = dict(run)
            for key in ('checkpoint', 'result'):
                item[key] = json.loads(item[key]) if item[key] is not None else None
            item['unresolved_executions'] = self.db.execute(
                "SELECT count(*) FROM executions WHERE run=? AND state IN ('started','unknown')", (item['id'],)).fetchone()[0]
            row['runs'].append(item)
        return row

    def executions(self, rid):
        self._run(rid)
        return [dict(row) for row in self.db.execute(
            'SELECT key,kind,state,resource,at FROM executions WHERE run=? ORDER BY at,rowid', (rid,))]

    def session(self, rid):
        self.clean()
        row = self.db.execute('SELECT * FROM agent_sessions WHERE run=?', (rid,)).fetchone()
        if row is None:
            return None
        if row['payload'] is None:
            raise ValueError('agent_session_expired_or_cleared_no_retry')
        return json.loads(row['payload'])

    def start_session(self, rid, node, epoch, contract, payload):
        with self.transaction():
            self._check(rid,node,epoch)
            row = self.db.execute('SELECT * FROM agent_sessions WHERE run=?',(rid,)).fetchone()
            if row:
                if row['contract'] != contract:
                    raise ValueError('agent_session_contract_changed')
                if row['payload'] is None:
                    raise ValueError('agent_session_expired_or_cleared_no_retry')
                return json.loads(row['payload'])
            self.db.execute('INSERT INTO agent_sessions VALUES(?,?,?,?)',
                            (rid,contract,encoded(payload),self.clock()))
            return payload

    def commit_action(self, rid, node, epoch, key, payload):
        """Persist the replay result and the no-repeat marker atomically."""
        serialized=encoded(payload)
        if len(serialized.encode())>128*1024:
            raise ValueError('agent_session_too_large')
        with self.transaction():
            row=self._check(rid,node,epoch)
            if not self.db.execute("UPDATE executions SET state='done' WHERE run=? AND key=? AND state='started'",
                                   (rid,key)).rowcount:
                raise ValueError('execution_already_settled')
            if not self.db.execute('UPDATE agent_sessions SET payload=? WHERE run=? AND payload IS NOT NULL',
                                   (serialized,rid)).rowcount:
                raise ValueError('agent_session_missing_or_cleared')
            self.db.execute('UPDATE runs SET checkpoint=?,payload_at=? WHERE id=?',
                            (encoded({'phase':'agent','committed_actions':len(payload['actions'])}),self.clock(),rid))
            self._event(row['delegation'],'agent_action_committed',rid)

    def yield_run(self, rid, node, epoch):
        with self.transaction():
            row=self._check(rid,node,epoch)
            self.db.execute("UPDATE executions SET state='unknown' WHERE run=? AND state='started'",(rid,))
            self.db.execute("UPDATE runs SET state='waiting_node',epoch=epoch+1,lease=0 WHERE id=?",(rid,))
            self._event(row['delegation'],'yielded',rid)

    def resolve(self, rid, key, outcome):
        """Owner-only acknowledgement after inspecting an unknown outcome.

        This releases a resource and allows continuation, but the original key
        remains non-retryable. Model billing reservations are a separate ledger.
        """
        if outcome not in ('done', 'rejected'):
            raise ValueError('invalid_resolution')
        with self.transaction():
            row = self._run(rid)
            if row['state'] == 'running' and row['lease'] > self.clock():
                raise ValueError('cannot_resolve_live_work')
            changed = self.db.execute("UPDATE executions SET state=? WHERE run=? AND key=? AND state='unknown'",
                                      (outcome, rid, key)).rowcount
            if not changed:
                raise ValueError('unknown_execution_not_found')
            self._event(row['delegation'], 'owner_resolved_' + outcome, rid)

    def clean(self, did=None):
        # Payload TTL and minimal no-retry markers have separate lifetimes.
        if did is None:
            self.db.execute('''UPDATE runs SET checkpoint=NULL,result=NULL,payload_at=NULL
                WHERE payload_at<?''', (self.clock()-30*86400,))
            self.db.execute('UPDATE agent_sessions SET payload=NULL WHERE at<?',(self.clock()-30*86400,))
            self.db.execute('''UPDATE runs SET checkpoint=NULL,result=NULL,payload_at=NULL
                WHERE id IN (SELECT run FROM agent_sessions WHERE payload IS NULL)''')
        else:
            self._delegation(did)
            self.db.execute('UPDATE runs SET checkpoint=NULL,result=NULL,payload_at=NULL WHERE delegation=?', (did,))
            self.db.execute('''UPDATE agent_sessions SET payload=NULL
                WHERE run IN (SELECT id FROM runs WHERE delegation=?)''',(did,))
        self.db.execute('DELETE FROM work_events WHERE at<?', (self.clock()-180*86400,))

    def list(self):
        return [dict(row) for row in self.db.execute(
            'SELECT id,node,state,created FROM delegations ORDER BY created DESC')]

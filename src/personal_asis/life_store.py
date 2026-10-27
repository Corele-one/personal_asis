"""AstrBot's owner-scoped life journal. Standard library, no model or Mac imports."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KINDS = ('journal', 'health', 'sleep_bed', 'sleep_wake', 'task')
TZ = ZoneInfo('Asia/Shanghai')


def timestamp(value=None):
    dt = datetime.now(timezone.utc) if value is None else datetime.fromisoformat(value)
    if dt.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return dt.astimezone(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class LifeStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        path.chmod(0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS records(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS changes(seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, due TEXT NOT NULL, origin TEXT NOT NULL, state TEXT NOT NULL);
        ''')

    def close(self):
        self.db.close()

    def get(self, record_id):
        row = self.db.execute('SELECT payload FROM records WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise ValueError('record_not_found')
        return json.loads(row[0])

    def _save(self, value):
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
        self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?)', (value['id'], payload))
        self.db.execute('INSERT INTO changes(id,payload) VALUES(?,?)', (value['id'], payload))
        return value

    def capture(self, platform, sender, message, text, occurred_at=None, origin='', *, capture_source='life_command'):
        from .life_intake import SOURCES
        if capture_source not in SOURCES:
            raise ValueError('invalid_capture_source')
        if not all(isinstance(v, str) and 0 < len(v) <= 512 for v in (platform, sender, message)):
            raise ValueError('invalid_message_identity')
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 16000 or '\x00' in text:
            raise ValueError('invalid_record_text')
        rid = digest(json.dumps([platform, sender, message]))
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.db.execute('SELECT 1 FROM records WHERE id=?', (rid,)).fetchone():
                current = self.get(rid)
                if current.get('capture_source') == 'conversation' and capture_source != 'conversation' and not current['deleted']:
                    current.update(capture_source=capture_source, revision=current['revision']+1, updated_at=timestamp())
                    self._save(current)
                return current, False
            at = timestamp(occurred_at)
            value = dict(id=rid, revision=1, platform=platform, sender=sender, message=message,
                         text=text, summary='', kind='journal', occurred_at=at,
                         day=datetime.fromisoformat(at).astimezone(TZ).date().isoformat(),
                         due_at=None, task_status='pending', deleted=False, updated_at=timestamp(), capture_source=capture_source)
            self._save(value)
        return value, True

    def organize(self, rid, *, kind, summary='', occurred_at=None, due_at=None, task_status='pending', origin=''):
        if kind not in KINDS or task_status not in ('pending', 'done', 'cancelled'):
            raise ValueError('invalid_record_kind_or_status')
        if not isinstance(summary, str) or len(summary.encode()) > 4000:
            raise ValueError('invalid_summary')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            value = self.get(rid)
            if value['deleted']:
                raise ValueError('record_deleted')
            at = timestamp(occurred_at or value['occurred_at'])
            due = timestamp(due_at) if due_at else None
            new = dict(value, kind=kind, summary=summary, occurred_at=at,
                       day=datetime.fromisoformat(at).astimezone(TZ).date().isoformat(),
                       due_at=due, task_status=task_status)
            if new == value:
                return value
            new.update(revision=value['revision'] + 1, updated_at=timestamp())
            self._save(new)
            # Reorganizing a record must not re-send a delivered/unknown reminder.
            if due and kind == 'task' and task_status == 'pending' and origin:
                self.db.execute("INSERT INTO reminders VALUES(?,?,?,'pending') ON CONFLICT(id) DO UPDATE SET due=excluded.due, origin=excluded.origin WHERE reminders.state='pending'", (rid, due, origin))
            else:
                self.db.execute("UPDATE reminders SET state='cancelled' WHERE id=? AND state='pending'", (rid,))
        return new

    def delete(self, rid):
        from .life_attention import LifeAttention
        attention = LifeAttention(self)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            value = self.get(rid)
            if value['deleted']:
                return value
            value.update(text='', summary='', due_at=None, deleted=True,
                         revision=value['revision']+1, updated_at=timestamp())
            if 'tracking' in value:
                value['tracking'] = {'habits': [], 'learning': []}
            attention.scrub(rid)
            # Remove prior plaintext snapshots; retain sequence and a tombstone for sync.
            self.db.execute('UPDATE changes SET payload=? WHERE id=?', (json.dumps(value), rid))
            self.db.execute('DELETE FROM reminders WHERE id=?', (rid,))
            return self._save(value)

    def export(self, after=0, limit=200):
        from .life_intake import sync_record
        if type(after) is not int or after < 0 or not 1 <= limit <= 200:
            raise ValueError('invalid_cursor')
        rows = self.db.execute('SELECT seq,payload FROM changes WHERE seq>? ORDER BY seq LIMIT ?', (after, limit)).fetchall()
        return dict(version=1, cursor=rows[-1]['seq'] if rows else after,
                    changes=[dict(seq=r['seq'], record=sync_record(json.loads(r['payload']))) for r in rows])

    def recent(self, limit=50, *, include_conversation=False):
        from .life_intake import visible
        rows = self.db.execute('SELECT payload FROM records ORDER BY rowid DESC')
        result = []
        for row in rows:
            r = json.loads(row[0])
            if not r['deleted'] and (include_conversation or visible(r)):
                result.append(r)
                if len(result) >= limit:
                    break
        return result

    def reconcile_intake(self):
        """Retire old implicit captures and invalid derived observations, retaining originals."""
        from .life_intake import source
        from .life_tracking import observations
        changed = conversations = corrections = 0
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for row in self.db.execute('SELECT payload FROM records').fetchall():
                r = json.loads(row[0]); mode = source(r)
                tracking = observations(r)
                if r.get('capture_source') == mode and r.get('tracking', {'habits':[], 'learning':[]}) == tracking:
                    continue
                if mode == 'conversation':conversations += 1
                if r.get('tracking', {'habits':[], 'learning':[]}) != tracking:corrections += 1
                r.update(capture_source=mode, tracking=tracking, revision=r['revision']+1, updated_at=timestamp())
                self._save(r); changed += 1
        return dict(changed=changed, excluded_conversations=conversations, corrected_tracking=corrections)

    def claim_reminders(self, now=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            rows = self.db.execute("SELECT * FROM reminders WHERE state='pending' AND due<=? ORDER BY due LIMIT 20", (timestamp(now),)).fetchall()
            for row in rows:
                self.db.execute("UPDATE reminders SET state='sending' WHERE id=?", (row['id'],))
        return [dict(r) for r in rows]

    def reminder_result(self, rid, state):
        if state not in ('sent', 'unknown'):
            raise ValueError('invalid_delivery_state')
        with self.db:
            self.db.execute("UPDATE reminders SET state=? WHERE id=? AND state='sending'", (state, rid))

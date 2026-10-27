"""Owner-authorized, persistent 01:00 / five-minute bedtime nudges. No LLM."""
from datetime import datetime, timedelta
import re

from .life_store import TZ, digest, timestamp


def owner_key(platform, sender):
    if not platform or not sender:
        raise ValueError('owner_binding_required')
    return digest(platform + '\0' + sender)


def is_goodnight(text):
    # Full-message whitelist: quotes, negations, questions and retrospective reports
    # must not accidentally silence reminders. Commands have their own explicit path.
    if any(c in text for c in '?？'):
        return False
    text = re.sub(r'[\s，。！,.!～~、；;：:🌙😴💤]', '', text)
    return bool(re.fullmatch(r'(?:晚安[啦了咯]?|(?:我要|我准备|准备|我去|去|我)?睡觉[了啦咯]|我?睡了){1,3}', text))


def next_deadline(now):
    local = datetime.fromisoformat(timestamp(now)).astimezone(TZ)
    deadline = local.replace(hour=1, minute=0, second=0, microsecond=0)
    if deadline <= local:
        deadline += timedelta(days=1)
    return timestamp(deadline.isoformat())


class BedtimeReminder:
    def __init__(self, store):
        self.db = store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS bedtime_policy(
          owner TEXT PRIMARY KEY, origin TEXT NOT NULL, enabled INTEGER NOT NULL,
          next_due TEXT NOT NULL, last_goodnight TEXT);
        CREATE TABLE IF NOT EXISTS bedtime_delivery(
          owner TEXT NOT NULL, due TEXT NOT NULL, state TEXT NOT NULL,
          attempted_at TEXT NOT NULL, PRIMARY KEY(owner,due));
        CREATE TABLE IF NOT EXISTS bedtime_ack(
          owner TEXT NOT NULL, message TEXT NOT NULL, PRIMARY KEY(owner,message));
        ''')

    def status(self, owner):
        row = self.db.execute('SELECT * FROM bedtime_policy WHERE owner=?', (owner,)).fetchone()
        return dict(row) if row else dict(enabled=False, next_due=None, last_goodnight=None)

    def set_enabled(self, owner, origin, enabled, now=None):
        if not origin:
            raise ValueError('private_origin_required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state = self.status(owner)
            due = next_deadline(now)
            # Enabling again must not undo a goodnight for the upcoming night.
            if state['last_goodnight'] and state['next_due'] > due:
                due = state['next_due']
            if state['enabled'] and enabled:
                due = state['next_due']
            self.db.execute('''INSERT INTO bedtime_policy VALUES(?,?,?,?,?)
                ON CONFLICT(owner) DO UPDATE SET origin=excluded.origin,
                enabled=excluded.enabled,next_due=excluded.next_due''',
                (owner, origin, int(enabled), due, state['last_goodnight']))
        return self.status(owner)

    def goodnight(self, owner, origin, now=None, message_id=''):
        at = timestamp(now)
        local = datetime.fromisoformat(at).astimezone(TZ)
        # An evening and the following morning share one sleep night, split at noon.
        night = local.replace(hour=1, minute=0, second=0, microsecond=0)
        if local.hour >= 12:
            night += timedelta(days=1)
        due = timestamp((night + timedelta(days=1)).isoformat())
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if message_id:
                inserted = self.db.execute('INSERT OR IGNORE INTO bedtime_ack VALUES(?,?)',
                                           (owner, digest(message_id)))
                if not inserted.rowcount:
                    return self.status(owner)
            state = self.status(owner)
            self.db.execute('''INSERT INTO bedtime_policy VALUES(?,?,?,?,?)
                ON CONFLICT(owner) DO UPDATE SET origin=excluded.origin,
                next_due=excluded.next_due,last_goodnight=excluded.last_goodnight''',
                (owner, origin, int(state['enabled']), due, at))
        return self.status(owner)

    def claim(self, owner, now=None):
        at = timestamp(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            state = self.status(owner)
            if not state['enabled'] or state['next_due'] > at:
                return None
            # One current nudge after downtime, never a catch-up flood. Persist the
            # attempt and the NEXT independent nudge before any network operation.
            inserted = self.db.execute("INSERT OR IGNORE INTO bedtime_delivery VALUES(?,?,'sending',?)",
                                       (owner, state['next_due'], at))
            next_due = timestamp((datetime.fromisoformat(at) + timedelta(minutes=5)).isoformat())
            self.db.execute('UPDATE bedtime_policy SET next_due=? WHERE owner=?', (next_due, owner))
            if not inserted.rowcount:
                return None
        return dict(owner=owner, origin=state['origin'], due=state['next_due'])

    def result(self, item, state):
        if state not in ('sent', 'unknown'):
            raise ValueError('invalid_delivery_state')
        with self.db:
            self.db.execute("UPDATE bedtime_delivery SET state=? WHERE owner=? AND due=? AND state='sending'",
                            (state, item['owner'], item['due']))

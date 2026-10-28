"""Owner-authorized, persistent 01:00 / ten-minute bedtime nudges. No LLM."""
from datetime import datetime, timedelta
import re

from .life_store import TZ, digest, timestamp

INTERVAL_MINUTES = 10


def night_start(at):
    local = datetime.fromisoformat(timestamp(at)).astimezone(TZ)
    start = local.replace(hour=12, minute=0, second=0, microsecond=0)
    return start - timedelta(days=1) if local.hour < 12 else start


def nudge_text(item, records=(), *, platform='', sender=''):
    """Use only this owner's current-night learning evidence, never infer wakefulness."""
    from .life_tracking import observations
    start = night_start(item['at'])
    topics = []
    for record in records:
        if record.get('platform') != platform or record.get('sender') != sender:
            continue
        at = datetime.fromisoformat(record['occurred_at'])
        if not start <= at <= datetime.fromisoformat(item['at']):
            continue
        for learning in observations(record)['learning']:
            topic = learning['topic'].strip()
            # Long text, markup and control characters do not belong in a nudge.
            if len(topic) <= 36 and not any(ord(c) < 32 or c in '[]<>`「」' for c in topic):
                topics.append((at, topic))
    number = item['number']
    if topics and number % 2:
        topic = max(topics, key=lambda pair: pair[0])[1]
        messages = (
            f'你前面记的「{topic}」，今晚先放一放吧。留一句下次从哪儿接着来，就可以安心收工了。',
            f'轻轻催你一下：「{topic}」可以留到睡醒再接着看，不用今晚把所有问题都解决。',
            f'「{topic}」不会跑掉，先把自己照顾好。要是还在忙，就找个方便停下来的地方收尾吧。',
        )
        body = messages[(start.date().toordinal() + number // 2) % len(messages)]
    else:
        messages = (
            '来轻轻催你收工。要是还在忙，先留个下次接着做的记号，今天就到这里吧。',
            '那个“再看一会儿”，今晚就先放过它吧。把屏幕放下，给自己一点慢慢安静下来的时间。',
            '不用等所有事都做完才休息。现在停在这里也可以，剩下的睡醒再说。',
            '来敲一下门：差不多该把今天合上啦。手头的事找个地方收尾，就去躺躺吧。',
            '要是还没歇下，就把下一步写一句，别让它一直挂在脑子里。今晚先照顾自己。',
            '今天不必再多完成一件事了。把手机放远一点，给自己留点不看屏幕的时间吧。',
            '再轻轻提醒一句：不用跟今天较劲到最后。能停下来的话，就安心去休息。',
            '如果已经睡下，这条醒来略过就好。还在忙的话，就把这当作今晚收工的小提示。',
        )
        body = messages[(start.date().toordinal() + number - 1) % len(messages)]
    # Keep the stop hint on the first nudge only; full controls remain in /life sleep.
    return body + ('\n准备睡了就跟我说声晚安，今晚我就不再催啦。' if number == 1 else '')


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
        # Upgrade an already scheduled five-minute follow-up without resetting
        # enablement, a goodnight, or the next night's 01:00 start. Idempotent.
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            for row in self.db.execute('''SELECT p.*, MAX(d.attempted_at) AS last_attempt
                    FROM bedtime_policy p JOIN bedtime_delivery d ON p.owner=d.owner
                    WHERE p.enabled=1 GROUP BY p.owner''').fetchall():
                next_due = timestamp((datetime.fromisoformat(row['last_attempt'])
                                      + timedelta(minutes=INTERVAL_MINUTES)).isoformat())
                if row['next_due'] < next_due and (not row['last_goodnight'] or row['last_goodnight'] <= row['last_attempt']):
                    self.db.execute('UPDATE bedtime_policy SET next_due=? WHERE owner=?', (next_due, row['owner']))

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
            next_due = timestamp((datetime.fromisoformat(at) + timedelta(minutes=INTERVAL_MINUTES)).isoformat())
            self.db.execute('UPDATE bedtime_policy SET next_due=? WHERE owner=?', (next_due, owner))
            if not inserted.rowcount:
                return None
            number = self.db.execute('''SELECT COUNT(*) FROM bedtime_delivery
                WHERE owner=? AND attempted_at>=? AND attempted_at<=?''',
                (owner, timestamp(night_start(at).isoformat()), at)).fetchone()[0]
        return dict(owner=owner, origin=state['origin'], due=state['next_due'], at=at, number=number)

    def result(self, item, state):
        if state not in ('sent', 'unknown'):
            raise ValueError('invalid_delivery_state')
        with self.db:
            self.db.execute("UPDATE bedtime_delivery SET state=? WHERE owner=? AND due=? AND state='sending'",
                            (state, item['owner'], item['due']))

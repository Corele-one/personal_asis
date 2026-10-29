"""Persistent goals, bounded briefing preparation and durable delivery reservations."""
from datetime import datetime, timedelta
import json
import re

from .life_store import TZ, digest, timestamp
from .life_tracking import HABITS, LifeTracking, clean


def local(now=None):
    return datetime.fromisoformat(timestamp(now)).astimezone(TZ)


def morning(at):
    return at.replace(hour=8, minute=0, second=0, microsecond=0)


class LifeAttention:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS focus_goals(id TEXT PRIMARY KEY, owner TEXT NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attention_policy(owner TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS attention_delivery(
          owner TEXT NOT NULL, day TEXT NOT NULL, state TEXT NOT NULL, payload TEXT NOT NULL,
          PRIMARY KEY(owner,day));
        ''')

    def goals(self, owner=None):
        rows = self.db.execute('SELECT payload FROM focus_goals' + (' WHERE owner=?' if owner else ''), (owner,) if owner else ())
        return [json.loads(r[0]) for r in rows]

    def policy(self, owner):
        r = self.db.execute('SELECT payload FROM attention_policy WHERE owner=?', (owner,)).fetchone()
        return json.loads(r[0]) if r else dict(enabled=False)

    def _policy(self, owner, value):
        self.db.execute('INSERT OR REPLACE INTO attention_policy VALUES(?,?)', (owner, json.dumps(value, ensure_ascii=False)))

    def configure(self, owner, origin, enabled=True, now=None):
        if not origin or not owner:
            raise ValueError('private_owner_origin_required')
        at = local(now)
        with self.db:
            value = self.policy(owner)
            if 'next_brief' not in value:
                days = (7 - at.weekday()) % 7 or 7
                value.update(next_brief=timestamp(morning(at + timedelta(days=3)).isoformat()),
                             next_weekly=timestamp(morning(at + timedelta(days=days)).isoformat()),
                             pause_until=None)
            value.update(enabled=bool(enabled), origin=origin)
            self._policy(owner, value)
        return value

    def bind_origin(self, owner, origin):
        value = self.policy(owner)
        if value.get('enabled') and value.get('origin') != origin:
            with self.db:
                value['origin'] = origin
                self._policy(owner, value)

    def pause(self, owner, mode, now=None):
        at = local(now)
        if mode == 'later':
            until = at + timedelta(hours=2)
        elif mode == 'week':
            until = morning(at + timedelta(days=7 - at.weekday()))
        elif mode == 'resume':
            until = None
        else:
            raise ValueError('invalid_attention_pause')
        with self.db:
            value = self.policy(owner)
            value['pause_until'] = timestamp(until.isoformat()) if until else None
            self._policy(owner, value)

    def goal(self, owner, source_id, *, goal_id='', title='', progress='', next_step='', blocker='',
             next_attention='', status='active', now=None):
        if status not in ('active', 'paused', 'done', 'stopped'):
            raise ValueError('invalid_goal_status')
        for v in (title, progress, next_step, blocker):
            clean(v)
        r = self.store.get(source_id)
        if r['deleted']:
            raise ValueError('record_deleted')
        if digest(r['platform'] + '\0' + r['sender']) != owner:
            raise ValueError('goal_owner_required')
        if not goal_id and not re.search(r'跟进|持续关注|帮我关注|帮我负责|我的目标|目标是', r['text']):
            raise ValueError('explicit_focus_request_required')
        updating = bool(goal_id)
        goal_id = goal_id or digest(owner + source_id)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            existing = self.db.execute('SELECT owner,payload FROM focus_goals WHERE id=?', (goal_id,)).fetchone()
            if updating and not existing:
                raise ValueError('goal_not_found')
            if existing and existing['owner'] != owner:
                raise ValueError('goal_owner_required')
            if existing and not updating:
                # Redelivering the original selection cannot reopen a completed
                # goal or manufacture a fresh progress update.
                return json.loads(existing['payload'])
            value = json.loads(existing['payload']) if existing else dict(id=goal_id, source_ids=[])
            if not existing and not title.strip():
                raise ValueError('goal_title_required')
            active = sum(g['status'] == 'active' and g['id'] != goal_id for g in self.goals(owner))
            if status == 'active' and active >= 3:
                raise ValueError('three_active_goals_limit')
            value.update(title=title or value.get('title', ''), progress=progress, next_step=next_step,
                         blocker=blocker, status=status, updated_at=timestamp(now),
                         next_attention=timestamp(next_attention) if next_attention else timestamp(morning(local(now) + timedelta(days=1)).isoformat()))
            references = list(dict.fromkeys(value['source_ids'] + [source_id]))
            value['source_ids'] = references if len(references) <= 32 else references[:1] + references[-31:]
            self.db.execute('INSERT OR REPLACE INTO focus_goals VALUES(?,?,?)', (goal_id, owner, json.dumps(value, ensure_ascii=False)))
        return value

    def prepare(self, owner, platform, sender, kind, now=None, mac=None):
        at = local(now)
        end = at.date() - timedelta(days=1)
        start = end - timedelta(days=6 if kind == 'weekly' else 2)
        if kind == 'weekly':
            start = at.date() - timedelta(days=at.weekday() + 7)
            end = start + timedelta(days=6)
        rows = LifeTracking(self.store).records(start.isoformat(), end.isoformat(), platform, sender)
        goals = [g for g in self.goals(owner) if g['status'] == 'active']
        from .life_briefing import gather, references, fallback, old_ideas
        home = self.store.path.parent
        recent_ideas = set()
        since = (at.date()-timedelta(days=14)).isoformat()
        for report in self.db.execute("SELECT payload FROM attention_delivery WHERE owner=? AND day>=? AND state IN ('sending','sent','unknown')",(owner,since)):
            recent_ideas.update(json.loads(report[0]).get('recalled_idea_keys',[]))
        ideas = old_ideas(self.store,platform,sender,start.isoformat(),end.isoformat(),
                          status_day=at.date().isoformat(),skip=recent_ideas)
        evidence, coverage = gather(home, rows, goals, start.isoformat(), end.isoformat(),ideas=ideas)
        heading = f"{'上周回顾' if kind == 'weekly' else '近几天简报'} · {start:%m/%d}–{end:%m/%d}"
        refs = references(evidence)
        source_ids = list(dict.fromkeys([r['id'] for r in rows] + [rid for g in goals for rid in g['source_ids']]
                                       + [r['record_id'] for r in refs if r.get('record_id')]))
        value = dict(kind=kind, start=start.isoformat(), end=end.isoformat(), heading=heading,
                     source_ids=source_ids, source_refs=refs, evidence=evidence,
                     source_owner=dict(platform=platform,sender=sender),
                     coverage=coverage, prepared_at=timestamp(now), generation='pending')
        value['body'] = fallback(value)
        return value

    def claim(self, owner, platform, sender, now=None, mac=None):
        at, stamp = local(now), timestamp(now)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            policy = self.policy(owner)
            if (not policy.get('enabled') or not 8 <= at.hour < 9
                    or policy.get('pause_until') and policy['pause_until'] > stamp):
                return None
            day = at.date().isoformat()
            if self.db.execute('SELECT 1 FROM attention_delivery WHERE owner=? AND day=?', (owner, day)).fetchone():
                return None
            weekly = at.weekday() == 0 and policy['next_weekly'] <= stamp
            periodic = policy['next_brief'] <= stamp
            due = [g for g in self.goals(owner) if g['status'] == 'active' and g['next_attention'] <= stamp
                   and g.get('reported_version') != g['updated_at']]
            if not (weekly or periodic or due):
                return None
            value = self.prepare(owner, platform, sender, 'weekly' if weekly else 'brief', now, mac)
            value['origin'] = policy['origin']
            self.db.execute('INSERT INTO attention_delivery VALUES(?,?,?,?)', (owner, day, 'sending', json.dumps({k:v for k,v in value.items() if k != 'evidence'}, ensure_ascii=False)))
            policy['next_brief'] = timestamp(morning(at + timedelta(days=3)).isoformat())
            # An overdue Monday report never becomes a backlog notification midweek.
            if weekly or policy['next_weekly'] <= stamp:
                policy['next_weekly'] = timestamp(morning(at + timedelta(days=7 - at.weekday())).isoformat())
            self._policy(owner, policy)
            for g in due:
                g['reported_version'] = g['updated_at']
                self.db.execute('UPDATE focus_goals SET payload=? WHERE id=?', (json.dumps(g, ensure_ascii=False), g['id']))
        return dict(value, day=day, owner=owner)

    def result(self, item, state):
        if state not in ('sent', 'unknown'):
            raise ValueError('invalid_delivery_state')
        with self.db:
            self.db.execute("UPDATE attention_delivery SET state=? WHERE owner=? AND day=? AND state='sending'", (state, item['owner'], item['day']))

    def valid(self, item):
        """Recheck after awaiting a model; corrections/withdrawals must win."""
        row = self.db.execute('SELECT state FROM attention_delivery WHERE owner=? AND day=?',
                              (item['owner'], item['day'])).fetchone()
        if not row or row['state'] != 'sending':
            return False
        policy = self.policy(item['owner'])
        if not policy.get('enabled') or policy.get('origin') != item['origin']:
            return False
        if policy.get('pause_until') and policy['pause_until'] > timestamp():
            return False
        if local().date().isoformat() != item['day'] or not 8 <= local().hour < 9:
            return False
        for ref in item.get('source_refs', []):
            if ref.get('record_id'):
                try:
                    record = self.store.get(ref['record_id'])
                except ValueError:
                    return False
                if record['deleted'] or record['revision'] != ref['revision']:
                    return False
            if ref.get('goal_id'):
                goal = next((g for g in self.goals(item['owner']) if g['id'] == ref['goal_id']), None)
                if not goal or goal['updated_at'] != ref['updated_at']:
                    return False
        from .life_briefing import shared_valid
        if not shared_valid(self.store.path.parent,item.get('source_refs',[])):
            return False
        # A new completion/cancellation received while generating also wins.
        if keys := item.get('recalled_idea_keys'):
            from .life_briefing import old_ideas
            bound = item['source_owner']
            current = old_ideas(self.store,bound['platform'],bound['sender'],item['start'],item['end'],
                                status_day=local().date().isoformat(),only_keys=set(keys))
            if not set(keys) <= {v['idea_key'] for v in current}:
                return False
        return True

    def save_body(self, item, body, generation):
        item.update(body=body, generation=generation)
        with self.db:
            self.db.execute("UPDATE attention_delivery SET payload=? WHERE owner=? AND day=? AND state='sending'",
                            (json.dumps({k:v for k,v in item.items() if k != 'evidence'}, ensure_ascii=False),
                             item['owner'], item['day']))

    def withdraw(self, item):
        with self.db:
            self.db.execute("UPDATE attention_delivery SET state='withdrawn',payload='{}' WHERE owner=? AND day=?",
                            (item['owner'], item['day']))

    def withdraw_stale_shared(self):
        from .life_briefing import shared_valid
        for row in self.db.execute('SELECT owner,day,payload FROM attention_delivery').fetchall():
            value = json.loads(row['payload'])
            if not shared_valid(self.store.path.parent, value.get('source_refs', [])):
                self.withdraw(dict(owner=row['owner'], day=row['day']))

    def dashboard(self):
        self.withdraw_stale_shared()
        goals = [{k:v for k,v in g.items() if k not in ('source_ids', 'reported_version')} for g in self.goals()]
        reports = []
        for row in self.db.execute('SELECT day,state,payload FROM attention_delivery ORDER BY day DESC LIMIT 8'):
            v = json.loads(row['payload'])
            if v.get('body'):
                reports.append(dict(day=row['day'], state=row['state'], body=v['body'], kind=v['kind']))
        return dict(goals=goals, reports=reports,
                    schedule='每3天 08:00–09:00 简报；周一回顾前一周，同日合并。催睡和明确时间事项独立。')

    def scrub(self, rid):
        """Called inside LifeStore.delete's transaction. Copies already sent remain external."""
        for g in self.goals():
            if rid in g['source_ids']:
                self.db.execute('DELETE FROM focus_goals WHERE id=?', (g['id'],))
        for row in self.db.execute('SELECT owner,day,payload FROM attention_delivery').fetchall():
            if rid in json.loads(row['payload']).get('source_ids', []):
                self.db.execute('UPDATE attention_delivery SET state=?,payload=? WHERE owner=? AND day=?',
                                ('withdrawn', '{}', row['owner'], row['day']))

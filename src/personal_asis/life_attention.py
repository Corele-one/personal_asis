"""Persistent goals and bounded, evidence-based preparation; no extra model loop."""
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
        source_ids = [r['id'] for r in rows]
        lines = [f"{'上周回顾' if kind == 'weekly' else '近几天简报'} · {start:%m/%d}–{end:%m/%d}"]
        observed = {}
        learning = []
        for r in rows:
            for h in r.get('tracking', {}).get('habits', []):
                key = (r['day'], h['habit'])
                if observed.get(key) == 'done' and h['status'] in ('planned', 'unknown'):
                    continue
                observed[key] = h['status']
            learning.extend((r, item) for item in r.get('tracking', {}).get('learning', []))
        completed = [f"{name} {sum(k[1] == key and v == 'done' for k,v in observed.items())} 天"
                     for key, name in HABITS.items() if any(k[1] == key and v == 'done' for k,v in observed.items())]
        if completed:
            lines.append('已记录的习惯：' + '，'.join(completed) + '。未记录的日期不计作未完成。')
        if learning:
            lines.append('学习记录整理：')
            for r, item in learning[-8:]:
                phase = {'start': '开始', 'progress': '进展', 'end': '结束'}[item['phase']]
                lines.append(f"• {r['day'][5:]} {phase} · {item['topic']}：{item['content'][:300]}")
            next_steps = list(dict.fromkeys(item['next_step'] for _,item in learning if item['next_step']))
            blockers = list(dict.fromkeys(item['blocker'] for _,item in learning if item['blocker']))
            if blockers:
                lines.append('待解决问题：' + '；'.join(blockers[-3:]))
            if next_steps:
                lines.append('按你记录整理的下次学习提纲：\n' + '\n'.join('□ ' + v for v in next_steps[-3:]))
        if goals:
            lines.append('当前关注事项：')
            for g in goals:
                source_ids.extend(g['source_ids'])
                lines.append('• ' + g['title'] + ('\n  进展：' + g['progress'] if g['progress'] else '')
                             + ('\n  卡点：' + g['blocker'] if g['blocker'] else '')
                             + ('\n  下一步：□ ' + g['next_step'] if g['next_step'] else '\n  下一步尚未确定，可以告诉我目前卡在哪。'))
        if len({r['day'] for r in rows if r.get('tracking')}) < 2:
            lines.append('这段时间可用的习惯／学习记录还不够，暂不判断趋势。可以运行 pi_sync 核对两端状态，并把未记录的学习或习惯补充给我。')
        stale = not mac
        if mac:
            try:
                stale = (at - local(mac['checked_at'])).total_seconds() > 3 * 86400
            except (KeyError, ValueError, TypeError):
                stale = True
        if stale:
            lines.append('Mac 最近同步状态较旧或尚不可用，方便时运行一次 pi_sync；它不会自动把笔记全文上传给我。')
        body = '\n\n'.join(lines)
        if len(body.encode()) > 12000:
            body = body.encode()[:11000].decode('utf-8', errors='ignore') + '\n（其余记录可在看板查看）'
        return dict(kind=kind, start=start.isoformat(), end=end.isoformat(), body=body,
                    source_ids=list(dict.fromkeys(source_ids)), prepared_at=timestamp(now))

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
            self.db.execute('INSERT INTO attention_delivery VALUES(?,?,?,?)', (owner, day, 'sending', json.dumps(value, ensure_ascii=False)))
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

    def dashboard(self):
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

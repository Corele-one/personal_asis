"""Evidence-backed habits and open-ended learning, derived from owner messages."""
from datetime import date, datetime
import json
import re

from .life_store import TZ, timestamp

HABITS = {'meditation': '冥想', 'reading': '阅读', 'early_sleep': '早睡', 'workout': '锻炼'}
STATES = ('done', 'not_done', 'planned', 'unknown')
PHASES = ('start', 'progress', 'end')


def clean(value, limit=2000):
    if not isinstance(value, str) or len(value.encode()) > limit or any(ord(c) < 32 and c not in '\n\t' for c in value):
        raise ValueError('invalid_tracking_text')
    return value.strip()


def validate(value, text):
    if not isinstance(value, dict) or set(value) != {'habits', 'learning'}:
        raise ValueError('invalid_tracking')
    if not isinstance(value['habits'], list) or len(value['habits']) > 4 or not isinstance(value['learning'], list) or len(value['learning']) > 8:
        raise ValueError('tracking_limit')
    seen = set()
    for h in value['habits']:
        if not isinstance(h, dict) or set(h) != {'habit', 'status', 'evidence'} or h['habit'] not in HABITS or h['status'] not in STATES or h['habit'] in seen:
            raise ValueError('invalid_habit')
        seen.add(h['habit'])
        evidence = clean(h['evidence'])
        if not evidence or evidence not in text:
            raise ValueError('tracking_evidence_required')
        # A quoted plan, question or negation is never evidence of completion.
        if h['status'] == 'done' and re.search(r'没|未|不|打算|计划|准备|(?<!冥)想|我要|要去|将要|明天|[?？“”「」"]', evidence):
            raise ValueError('habit_completion_not_supported')
    for item in value['learning']:
        if not isinstance(item, dict) or set(item) != {'phase', 'topic', 'content', 'blocker', 'next_step', 'evidence'} or item['phase'] not in PHASES:
            raise ValueError('invalid_learning')
        for key in ('topic', 'content', 'blocker', 'next_step', 'evidence'):
            clean(item[key], 300 if key == 'topic' else 2000)
        if any(c in item['topic'] for c in '\r\n'):
            raise ValueError('invalid_learning_topic')
        if not item['topic'].strip() or not item['evidence'].strip() or item['evidence'] not in text:
            raise ValueError('learning_evidence_required')
    return value


def infer(text):
    """High precision fallback; richer wording is organized by AstrBot's native model."""
    text = re.sub(r'^/?life\s+', '', text)
    result = {'habits': [], 'learning': []}
    aliases = {'meditation': r'冥想|meditat(?:ion|ed)', 'reading': r'阅读|读书',
               'early_sleep': r'早睡', 'workout': r'锻炼|健身|运动|workout'}
    for clause in re.split(r'[，,；;。\n]', text):
        clause = clause.strip()
        if not clause or re.search(r'[?？“”「」"]|他说|她说|别人|昨天|前天|明天', clause):
            continue
        for key, alias in aliases.items():
            if not re.search(alias, clause, re.I):
                continue
            status = None
            if re.search(r'没(?:有)?|尚未|还未|未完成|不再|不会', clause):
                status = 'not_done'
            elif re.search(r'打算|计划|准备|(?<!冥)想|我要|要去|等会|待会', clause):
                status = 'planned'
            elif re.search(r'完成|做完|读完|结束|打卡|(?:冥想|阅读|读书|锻炼|健身|运动|早睡)了', clause):
                status = 'done'
            if status:
                if status == 'done' and re.search(r'不', clause):
                    continue
                result['habits'] = [h for h in result['habits'] if h['habit'] != key]
                result['habits'].append(dict(habit=key, status=status, evidence=clause))
        match = re.fullmatch(r'(?:我)?(?:现在|今天)?(?:开始学习|开始学|开始复习|开始研究)\s*[:：]?\s*(.+)', clause)
        phase = 'start'
        if not match:
            match = re.fullmatch(r'(?:我)?(?:今天)?(?:学完了|学习结束|结束学习|复习完了)\s*[:：]?\s*(.+)', clause)
            phase = 'end'
        if match and not re.search(r'打算|计划|明天|[?？]', clause):
            result['learning'].append(dict(phase=phase, topic=match[1].strip(), content=clause,
                                           blocker='', next_step='', evidence=clause))
    return result


class LifeTracking:
    def __init__(self, store):
        self.store = store

    def update(self, rid, value):
        with self.store.db:
            self.store.db.execute('BEGIN IMMEDIATE')
            r = self.store.get(rid)
            if r['deleted']:
                raise ValueError('record_deleted')
            validate(value, r['text'])
            if r.get('tracking') == value:
                return r
            r.update(tracking=value, revision=r['revision'] + 1, updated_at=timestamp())
            return self.store._save(r)

    def auto(self, r):
        # Redelivery or later life_organize must not replace a model correction.
        if 'tracking' not in r:
            value = infer(r['text'])
            if value['habits'] or value['learning']:
                return self.update(r['id'], value)
        return r

    def records(self, start, end, platform=None, sender=None):
        date.fromisoformat(start); date.fromisoformat(end)
        rows = self.store.db.execute("SELECT payload FROM records WHERE json_extract(payload,'$.day') BETWEEN ? AND ? ORDER BY json_extract(payload,'$.occurred_at'),rowid", (start, end))
        return [r for row in rows if not (r := json.loads(row[0]))['deleted']
                and (platform is None or r['platform'] == platform) and (sender is None or r['sender'] == sender)]

    def day(self, day=None):
        day = day or datetime.now(TZ).date().isoformat()
        habits = {key: dict(habit=key, label=label, status='unknown', evidence='', record_id=None)
                  for key, label in HABITS.items()}
        learning, opened = [], []
        for r in self.records(day, day):
            for h in r.get('tracking', {}).get('habits', []):
                # A later intention does not erase a reported completion.
                if habits[h['habit']]['status'] == 'done' and h['status'] in ('planned', 'unknown'):
                    continue
                habits[h['habit']].update(h, record_id=r['id'], occurred_at=r['occurred_at'])
            for item in r.get('tracking', {}).get('learning', []):
                entry = dict(item, record_id=r['id'], occurred_at=r['occurred_at'], start_record_id=None)
                if item['phase'] == 'start':
                    opened.append(entry)
                elif item['phase'] == 'end':
                    matches = [v for v in opened if v['topic'].casefold() == item['topic'].casefold()]
                    if len(matches) == 1:
                        entry['start_record_id'] = matches[0]['record_id']
                        opened.remove(matches[0])
                learning.append(entry)
        return dict(day=day, habits=list(habits.values()), learning=learning,
                    open_sessions=[v['record_id'] for v in opened])

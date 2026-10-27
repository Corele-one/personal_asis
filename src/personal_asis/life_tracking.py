"""Evidence-backed habits and open-ended learning, derived from owner messages."""
from datetime import date, datetime
import json
import re

from .life_store import TZ, timestamp

HABITS = {'meditation': '冥想', 'reading': '阅读', 'early_sleep': '早睡', 'workout': '锻炼'}
STATES = ('done', 'not_done', 'planned', 'unknown')
PHASES = ('start', 'progress', 'end')
ALIASES = {'meditation': r'冥想|meditat(?:ion|ed)', 'reading': r'阅读|读书|看书|读完|看完|读了',
           'early_sleep': r'早睡', 'workout': r'锻炼|健身|运动|workout'}
REQUIREMENT = r'要求|作业说明|任务说明|实验指导|实践作业|课程作业|评分标准|参考答案|示例|例如|他说|她说|老师说'


def evidence_text(record):
    notes = record.get('feedback_notes', [])
    if not isinstance(notes,list) or len(notes) > 8:
        raise ValueError('invalid_feedback_evidence')
    for note in notes:
        if not isinstance(note,dict) or set(note) != {'id','text','at'}:
            raise ValueError('invalid_feedback_evidence')
        clean(note['text'],4000)
    return record['text'] + ''.join('\n本人纠正：'+note['text'] for note in notes)


def contexts(text, evidence):
    # Validate the whole containing sentence, not a model-selected substring
    # such as “阅读完成” taken out of a teacher's assignment requirements.
    for clause in re.split(r'[。！？\n;；]', text):
        if evidence.strip() in clause or clause.strip() and clause.strip() in evidence:
            yield clause


def supported(text, item, kind):
    for clause in contexts(text, item['evidence']):
        clause = re.sub(r'^/?life\s+', '', clause.strip())
        if re.search(r'[?？“”「」"]', clause):
            continue
        if re.search(REQUIREMENT + r'|布置|同学|朋友|同事|他(?:已|读|学|完成)|她(?:已|读|学|完成)', text):
            # A separate actual self report can coexist with quoted requirements.
            actual = re.search(r'我(?:今天|刚刚|已经|刚|现在|这次|昨晚|上午|下午|晚上|又|也|确实|认真地|认真|\s)*(?:读完了|读了|看完了|学了|学完了|学习了|复习了|完成了|做完了)', clause)
            if not actual or re.search(r'要求|让我|需要|建议|希望', clause[:actual.start()][-8:]) or re.search(r'示例|例如|参考答案',text):
                continue
        if kind == 'habit':
            habit, status = item['habit'], item['status']
            action_clause = re.sub(r'《[^》]*》','（书名）',item['evidence'])
            if not re.search(ALIASES[habit], action_clause, re.I):
                continue
            if habit == 'reading' and re.search(r'实践|作业|实验指导|题目|文档|代码|任务说明|教材要求', clause):
                continue
            if status == 'done':
                if re.search(r'没|未|打算|计划|准备|我要|要去|将要|明天', clause):
                    continue
                if not re.search(r'完成|做完|读完|看完|读了|结束|打卡|(?:冥想|阅读|读书|看书|锻炼|健身|运动|早睡)了', clause):
                    continue
                # Completing a reading task about meditation is not completing
                # meditation. Tie completion to the specific reported activity.
                activity = ALIASES[habit]
                if habit != 'reading' and not re.search(
                        r'(?:'+activity+r')(?:了|完成|结束|打卡|[\d一二三四五六七八九十分钟小时 ]{1,16}(?:完成|结束))'
                        r'|(?:完成了?|结束了?|做完了?)(?:今天的|一次|一轮|[\d一二三四五六七八九十分钟小时的 ]{0,16})(?:'+activity+r')',
                        action_clause,re.I):
                    continue
            elif status == 'not_done' and not re.search(r'没|未|不',clause):
                continue
            elif status == 'planned' and not re.search(r'计划|准备|打算|想|要|等会|待会',clause):
                continue
        else:
            proof = item['evidence']
            if not re.search(r'学|复习|研究|实验|实践|作业|练习|阅读|看了|读了|读完|卡在|不理解|不明白|搞懂|理解了|弄懂', proof):
                continue
            if (re.search(r'打算|计划|准备|想要|将要|明天|待会|等会',proof)
                    and not re.search(r'已经|正在|学了|学完了|学习了|复习了|研究了|做完了|完成了',proof)):
                continue
        return True
    return False


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
        if not supported(text,h,'habit'):
            raise ValueError('habit_self_report_required')
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
        if not supported(text,item,'learning'):
            raise ValueError('learning_self_report_required')
    return value


def observations(record):
    """Read gates also protect old snapshots until their next explicit migration."""
    from .life_intake import is_entry
    result = dict(habits=[], learning=[])
    if record['deleted'] or not is_entry(record):
        return result
    for name in result:
        for item in record.get('tracking', {}).get(name, []):
            one = dict(habits=[], learning=[]);one[name] = [item]
            try:
                validate(one,evidence_text(record))
            except (ValueError, KeyError, TypeError):
                continue
            result[name].append(item)
    return result


def infer(text):
    """High precision fallback; richer wording is organized by AstrBot's native model."""
    text = re.sub(r'^/?life\s+', '', text)
    result = {'habits': [], 'learning': []}
    aliases = ALIASES
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
                h = dict(habit=key,status=status,evidence=clause)
                if supported(text,h,'habit'):
                    result['habits'] = [h for h in result['habits'] if h['habit'] != key]
                    result['habits'].append(h)
        match = re.fullmatch(r'(?:我)?(?:现在|今天)?(?:开始学习|开始学|开始复习|开始研究)\s*[:：]?\s*(.+)', clause)
        phase = 'start'
        if not match:
            match = re.fullmatch(r'(?:我)?(?:今天)?(?:学完了|学习结束|结束学习|复习完了)\s*[:：]?\s*(.+)', clause)
            phase = 'end'
        if match and not re.search(REQUIREMENT + r'|打算|计划|明天|[?？]', text):
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
            from .life_intake import is_entry
            if not is_entry(r):
                raise ValueError('explicit_life_entry_required')
            validate(value, evidence_text(r))
            if r.get('tracking') == value:
                return r
            r.update(tracking=value, revision=r['revision'] + 1, updated_at=timestamp())
            return self.store._save(r)

    def auto(self, r):
        # Redelivery or later life_organize must not replace a model correction.
        from .life_intake import is_entry
        if is_entry(r) and 'tracking' not in r:
            value = infer(r['text'])
            if value['habits'] or value['learning']:
                return self.update(r['id'], value)
        return r

    def records(self, start, end, platform=None, sender=None):
        date.fromisoformat(start); date.fromisoformat(end)
        rows = self.store.db.execute("SELECT payload FROM records WHERE json_extract(payload,'$.day') BETWEEN ? AND ? ORDER BY json_extract(payload,'$.occurred_at'),rowid", (start, end))
        from .life_intake import is_entry
        return [dict(r,tracking=observations(r)) for row in rows if not (r := json.loads(row[0]))['deleted'] and is_entry(r)
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

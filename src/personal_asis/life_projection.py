"""Managed Habit/Learning projections inside existing Life daily sections."""
from datetime import datetime
import json
from pathlib import Path
import re

from .life_store import TZ, digest
from .life_tracking import HABITS

LABELS = {'done': '已完成（自报）', 'not_done': '明确未完成', 'planned': '计划', 'unknown': '待核对'}
ALIASES = {'meditation': r'(?:🧘\S*\s*)?(?:meditation|冥想)', 'reading': r'(?:📖\s*)?(?:reading|阅读|读书)',
           'early_sleep': r'(?:(?:🛏|🛌)\S*\s*)?(?:早睡|early sleep)', 'workout': r'(?:🏋\S*\s*)?(?:workout|锻炼|健身)'}


def section(text, name):
    label = r'(?:⚛️\s*)?(?:Habits|Habit)' if name == 'habits' else r'(?:📖\s*)?(?:Learning|Study)'
    found = re.search(r'^(#{1,3})[ \t]+' + label + r'[ \t]*$', text, re.M | re.I)
    if not found:
        text = text.rstrip() + '\n\n### ' + ('⚛️Habits' if name == 'habits' else '📖Learning') + '\n'
        found = re.search(r'^(#{1,3})[ \t]+' + label + r'[ \t]*$', text, re.M | re.I)
    following = re.search(r'^#{1,' + str(len(found[1])) + r'}[ \t]+', text[found.end():], re.M)
    end = found.end() + following.start() if following else len(text)
    return text, found.end(), end


def replace_block(text, name, day, content):
    prefix = f'<!-- asis-{name}:{day}:'
    pattern = re.compile(r'^' + re.escape(prefix) + r'start -->\n.*?^' + re.escape(prefix) + r'end -->\n?', re.M | re.S)
    matches = list(pattern.finditer(text))
    if len(matches) > 1 or text.count(prefix) != 2 * len(matches):
        raise ValueError('damaged_activity_block')
    if not content:
        return pattern.sub('', text)
    rendered = prefix + 'start -->\n' + content + '\n' + prefix + 'end -->\n'
    if matches:
        return pattern.sub(lambda _: rendered, text)
    text, _, end = section(text, name)
    return text[:end].rstrip() + '\n\n' + rendered + '\n' + text[end:]


def plan(state, root, daily, journal_files=()):
    from .life_sync import safe_target
    files = {str(f['path']): dict(f) for f in journal_files}
    old_receipts = state.get('activity_applied', {})
    days = set(old_receipts) | {r['day'] for r in state['records'].values() if r.get('tracking')}
    receipts = {}
    for day in sorted(days):
        path = safe_target(root, str(Path(daily) / (day + '.md')))
        key = str(path)
        if key not in files:
            before = path.read_bytes() if path.exists() else b''
            if len(before) > 2_000_000:
                raise ValueError('daily_file_too_large')
            files[key] = dict(path=path, before=before, after=before.decode())
        f = files[key]
        records = sorted((r for r in state['records'].values() if r['day'] == day and not r['deleted']),
                         key=lambda r: (r['occurred_at'], r['id']))
        habits, learning = {}, []
        for r in records:
            for h in r.get('tracking', {}).get('habits', []):
                if habits.get(h['habit'], {}).get('status') == 'done' and h['status'] in ('planned', 'unknown'):
                    continue
                habits[h['habit']] = h
            for item in r.get('tracking', {}).get('learning', []):
                at = datetime.fromisoformat(r['occurred_at']).astimezone(TZ).strftime('%H:%M')
                phase = {'start': '开始', 'progress': '进展', 'end': '结束'}[item['phase']]
                quote = lambda s: '\n'.join('> ' + v for v in s.replace('\r', '').split('\n'))
                line = f"#### {at} · {phase} · {item['topic']}\n\n" + quote(item['evidence'])
                if item['content'] != item['evidence']:
                    line += '\n\n整理（可修正）：\n' + quote(item['content'])
                if item['blocker']:
                    line += '\n\n待解决：\n' + quote(item['blocker'])
                if item['next_step']:
                    line += '\n\n下一步：\n' + quote(item['next_step'])
                learning.append(line)
        prior = old_receipts.get(day, {}).get('checkboxes', {})
        cells = {}
        # Reconcile only cells previously changed by this sync. Handwritten checks
        # and unrelated text remain authoritative and are never reset from absence.
        if habits or prior:
            text, start, end = section(f['after'], 'habits')
            body = text[start:end]
            for name, alias in ALIASES.items():
                pattern = re.compile(r'^([ \t]*- \[)([ xX])' + r'(\][ \t]+' + alias + r'[ \t]*)$', re.M | re.I)
                matches = list(pattern.finditer(body))
                if len(matches) > 1:
                    raise ValueError('ambiguous_habit_checkbox')
                if not matches:
                    continue
                match = matches[0]
                old = prior.get(name)
                current = match[2]
                desired = None
                if name in habits and habits[name]['status'] == 'done':
                    desired = 'x'
                elif old and current == old['after']:
                    desired = old['before']
                if desired is not None:
                    original = old['before'] if old and current == old['after'] else current
                    if desired != original:
                        cells[name] = dict(before=original, after=desired)
                    body = body[:match.start(2)] + desired + body[match.end(2):]
            f['after'] = text[:start] + body + text[end:]
        habit_text = '\n'.join(f"- [{'x' if h['status'] == 'done' else ' '}] {HABITS[k]} · {LABELS[h['status']]}\n  > "
                               + h['evidence'].replace('\n', '\n  > ') for k,h in habits.items())
        f['after'] = replace_block(f['after'], 'habits', day, habit_text)
        f['after'] = replace_block(f['after'], 'learning', day, '\n\n'.join(learning))
        receipts[day] = dict(checkboxes=cells, fingerprint=digest(json.dumps([habits, learning], ensure_ascii=False)))
    return [f for f in files.values() if f['before'] != f['after'].encode()], receipts

"""Managed Habit/Learning projections inside existing Life daily sections."""
from datetime import datetime
import json
from pathlib import Path
import re

from .life_store import TZ, digest
from .life_tracking import HABITS, observations
from . import life_freewrite as markdown
from .life_journal import location, locate

VERSION = 2

LABELS = {'done': '已完成（自报）', 'not_done': '明确未完成', 'planned': '计划', 'unknown': '待核对'}
ALIASES = {'meditation': r'(?:🧘\S*\s*)?(?:meditation|冥想)', 'reading': r'(?:📖\s*)?(?:reading|阅读|读书)',
           'early_sleep': r'(?:(?:🛏|🛌)\S*\s*)?(?:早睡|early sleep)', 'workout': r'(?:🏋\S*\s*)?(?:workout|锻炼|健身)'}


def section(text, name):
    label = r'(?:⚛️\s*)?(?:Habits|Habit)' if name == 'habits' else r'(?:📖\s*)?(?:Learning|Study)'
    headings = list(markdown.headings(text))
    found = [h for h in headings if h[2] <= 3 and re.fullmatch(label,h[3],re.I)]
    if len(found) > 1:
        raise ValueError('ambiguous_activity_section')
    if not found:
        # Reuse the known daily two-column template when a heading is missing.
        surface = list(markdown.surface_lines(text))
        starts = [p for p,line in surface if re.match(r'^--- start-multi-column: daily_habits_learning\s*$',line)]
        if len(starts) > 1:
            raise ValueError('ambiguous_activity_section')
        boundaries = [(p,line) for p,line in surface if starts and p > starts[0]]
        marker = r'^--- end-column(?: ---)?\s*$' if name == 'habits' else r'^--- end-multi-column(?: ---)?\s*$'
        pos = next((p for p,line in boundaries if re.match(marker,line)),None)
        if pos is None:
            pos = markdown.footer_position(text)
            pos = min(pos,next((p for p,_,_,title in headings if title == 'End-of-Day Checklist'),len(text)))
        text = markdown.splice(text,pos,'### ' + ('⚛️Habits' if name == 'habits' else '📖Learning') + '\n')
        return section(text,name)
    _,start,level,_ = found[0]
    end = next((p for p,_,n,title in headings if p > start and (n <= level or title == 'End-of-Day Checklist')),len(text))
    end = min(end,markdown.footer_position(text,start,end))
    end = next((p for p,line in markdown.surface_lines(text) if start <= p < end and re.fullmatch(
        r'[ \t]{0,3}---(?:[ \t]+end-(?:multi-)?column(?:[ \t]+---)?)?[ \t]*\r?\n?',line)),end)
    return text,start,end


def remove_block(text, name, day, receipt):
    prefix = f'<!-- asis-{name}:{day}:'
    pattern = re.compile(r'^' + re.escape(prefix) + r'start -->\n.*?^' + re.escape(prefix) + r'end -->\n?', re.M | re.S)
    surface = {p for p,_ in markdown.surface_lines(text)}
    matches = [match for match in pattern.finditer(text) if match.start() in surface]
    count = sum(bool(re.fullmatch(re.escape(prefix)+r'(?:start|end) -->\r?\n?',line)) for _,line in markdown.surface_lines(text))
    if len(matches) > 1 or count != 2 * len(matches):
        raise ValueError('damaged_activity_block')
    old = receipt.get('locations',{}).get(name)
    if old and matches:
        raise ValueError('damaged_activity_block')
    if matches:
        match = matches[0];start,end = match.span()
    elif old:
        start,end = locate(text,old)
    else:
        return text,None
    owned = dict(start=start,text=text[start:end],file_hash=digest(text))
    replacement = ''
    if old:
        _,_,limit = section(text,name)
        limit = min(limit,next((p for p,_,level,_ in markdown.headings(text) if p >= end and level <= 4),len(text)))
        if text[end:limit].strip():
            titles = [h for h in markdown.headings(text[start:end]) if h[2] == 4]
            if titles:
                # The following handwritten paragraph still belongs to this
                # heading, even after its synchronized observation is removed.
                a,b,_,_ = titles[-1]
                replacement = text[start+a:start+b]+'\n\n'
    return text[:start]+replacement+text[end:],owned


def learning_text(items):
    groups = {}
    for at,item in items:
        groups.setdefault(item['topic'],[]).append((at,item))
    result = []
    for topic,entries in groups.items():
        title = re.sub(r'[\r\n#<>`\[\]]','',topic).strip()
        lines = ['#### '+title,'']
        for at,item in entries:
            phase = {'start':'开始','progress':'进展','end':'结束'}[item['phase']]
            lines.append(f'- **{at} · {phase}**  ')
            body = markdown.block({'text':item['evidence']}).rstrip('\n')
            lines.extend('  '+line for line in body.splitlines())
            for key,label in (('blocker','待解决'),('next_step','下一步')):
                if item[key]:
                    safe = markdown.block({'text':item[key]}).rstrip('\n')
                    lines.extend('  '+line for line in (label+'：'+safe).splitlines())
        result.append('\n'.join(lines))
    return '\n\n'.join(result)+'\n' if result else ''


def remove_placeholders(text):
    text,start,end = section(text,'learning')
    body = text[start:end]
    lines = re.findall(r'^- \[ \] (Missing|C\+\+|Research)[ \t]*$',body,re.M)
    if set(lines) == {'Missing','C++','Research'} and len(lines) == 3:
        body = re.sub(r'^- \[ \] (?:Missing|C\+\+|Research)[ \t]*\r?\n?', '', body,flags=re.M)
        return text[:start]+body+text[end:]
    return text


def plan(state, root, daily, journal_files=(), *, allowed=None):
    from .life_sync import safe_target
    files = {str(f['path']): dict(f) for f in journal_files}
    old_receipts = state.get('activity_applied', {})
    days = set(old_receipts) | {r['day'] for r in state['records'].values() if r.get('tracking')}
    receipts = {}
    for day in sorted(days):
        relative = str(Path(daily) / (day + '.md'))
        if allowed is not None and not allowed(relative):
            raise ValueError('daily_target_excluded')
        path = safe_target(root, relative)
        key = str(path)
        if key not in files:
            before = path.read_bytes() if path.exists() else b''
            if len(before) > 2_000_000:
                raise ValueError('daily_file_too_large')
            files[key] = dict(path=path, before=before, after=before.decode())
        f = files[key]
        previous = old_receipts.get(day,{})
        for name in ('habits','learning'):
            _,owned = remove_block(f['before'].decode(),name,day,previous)
            f['after'],_ = remove_block(f['after'],name,day,previous)
            if owned:
                f.setdefault('activity_before',{})[name] = dict(owned,path=relative)
        records = sorted((r for r in state['records'].values() if r['day'] == day and not r['deleted']),
                         key=lambda r: (r['occurred_at'], r['id']))
        habits, learning = {}, []
        for r in records:
            tracking = observations(r)
            for h in tracking['habits']:
                if habits.get(h['habit'], {}).get('status') == 'done' and h['status'] in ('planned', 'unknown'):
                    continue
                habits[h['habit']] = h
            for item in tracking['learning']:
                at = datetime.fromisoformat(r['occurred_at']).astimezone(TZ).strftime('%H:%M')
                learning.append((at,item))
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
        rendered = {'habits':habit_text+'\n' if habit_text else '', 'learning':learning_text(learning)}
        if rendered['learning']:
            f['after'] = remove_placeholders(f['after'])
        for name,content in rendered.items():
            if not content:
                continue
            f['after'],start,end = section(f['after'],name)
            matches = list(re.finditer(re.escape(content),f['after'][start:end]))
            if len(matches) > 1:
                raise ValueError('journal_text_ambiguous')
            if not matches:
                f['after'] = markdown.splice(f['after'],end,content)
        locations = {}
        for name,content in rendered.items():
            if not content:
                continue
            _,start,end = section(f['after'],name)
            pos = f['after'].find(content,start,end)
            if pos < 0:
                raise ValueError('journal_projection_missing')
            locations[name] = location(relative,f['after'],pos,content)
        f['activity_after'] = locations
        receipts[day] = dict(version=VERSION, locations=locations, checkboxes=cells,
                             fingerprint=digest(json.dumps([habits, learning], ensure_ascii=False)))
    return [f for f in files.values() if f['before'] != f['after'].encode()], receipts

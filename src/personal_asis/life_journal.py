"""Marker-free diary projection; ownership and interrupted writes stay private."""
import copy
import hashlib
from pathlib import Path
import re

from . import life_freewrite as prose

VERSION = 4


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def location(path, text, start, body):
    return dict(path=path, start=start, text=body, file_hash=digest(text))


def locate(text, loc):
    body, start = loc['text'], loc['start']
    if digest(text) == loc['file_hash'] and text[start:start+len(body)] == body:
        return start, start+len(body)
    matches = [m.start() for m in re.finditer(re.escape(body),text)
               if m.start() == 0 or text[m.start()-1] == '\n']
    if len(matches) > 1:
        raise ValueError('journal_text_ambiguous')
    if not matches:
        raise ValueError('journal_text_edited')
    return matches[0], matches[0]+len(body)


def plan(state, root, daily, *, editor=None, allowed=None):
    from .life_sync import safe_target, local_time, projected
    records, old = state['records'], state['applied']
    loaded = {}
    def read_file(relative):
        if relative not in loaded:
            path = safe_target(root,relative)
            if allowed is not None and not allowed(relative):
                raise ValueError('daily_target_excluded')
            raw = path.read_bytes() if path.exists() else b''
            if len(raw) > 2_000_000:
                raise ValueError('daily_file_too_large')
            loaded[relative] = raw
        return loaded[relative]
    changed = {rid for rid,r in records.items() if not (old.get(rid,{}).get('projection') == VERSION
        and old[rid]['revision'] == r['revision'] and old[rid]['present'] == projected(r)
        and (not editor or not projected(r) or old[rid].get('layout') == editor.version))}
    for rid in list(changed):
        if rid not in old and not projected(records[rid]):
            relative = str(Path(daily)/(records[rid]['day']+'.md'))
            if ('<!-- astrbot:'+rid+':').encode() not in read_file(relative):
                changed.remove(rid)
    if not changed:
        return [], []
    paths = set()
    for rid in changed:
        paths.add(str(Path(daily)/(records[rid]['day']+'.md')))
        receipt = old.get(rid,{})
        if receipt.get('path'):
            paths.add(receipt['path'])
        paths.update(loc['path'] for loc in receipt.get('locations',[]))
    # Rebuild only affected files, including their unchanged synchronized prose.
    files, receipts = [], {}
    for relative in sorted(paths):
        path = safe_target(root,relative)
        raw = read_file(relative)
        before = raw.decode('utf-8'); text = before
        spans, owned_before, involved = set(), {}, set()
        desired, adoptions = [], []
        for rid,r in sorted(records.items(),key=lambda item:(item[1]['day'],local_time(item[1]['occurred_at']),item[0])):
            target = str(Path(daily)/(r['day']+'.md'))
            prior = old.get(rid,{})
            locs = [loc for loc in prior.get('locations',[]) if loc['path'] == relative]
            pattern = re.compile(r'^<!-- astrbot:'+rid+r':start -->\n.*?^<!-- astrbot:'+rid+r':end -->\n?',re.M|re.S)
            legacy = list(pattern.finditer(before))
            starts = len(re.findall(r'^<!-- astrbot:'+rid+r':start -->$',before,re.M))
            ends = len(re.findall(r'^<!-- astrbot:'+rid+r':end -->$',before,re.M))
            if len(legacy)>1:
                raise ValueError('duplicate_sync_blocks')
            if starts != len(legacy) or ends != len(legacy):
                raise ValueError('damaged_sync_block')
            for match in legacy:
                spans.add((match.start(),match.end()))
                owned_before[rid] = location(relative,before,match.start(),match[0])
            for loc in locs:
                start,end = locate(before,loc)
                spans.add((start,end))
                owned_before[rid] = location(relative,before,start,before[start:end])
            if target == relative and projected(r):
                involved.add(rid)
                body = prose.block(r)
                # Recovery when a write reached the file but its receipt did not.
                # Adopt an exact, unique paragraph only inside the intended section.
                bounds = prose.subsection(before)
                if not legacy and not locs and bounds:
                    adoptions.append((rid,body,bounds))
                desired.append((rid,body))
            if legacy or locs or (rid in old and prior.get('path') == relative) or (target == relative and projected(r)):
                involved.add(rid)
        for rid,body,bounds in sorted(adoptions,key=lambda item:len(item[1]),reverse=True):
            matches = []
            for match in re.finditer(re.escape(body),before[bounds[0]:bounds[1]]):
                start = match.start()+bounds[0];end = start+len(body)
                if ((start == 0 or before[start-1] == '\n')
                        and (end >= bounds[1] or before[end] == '\n')
                        and not any(start < b and a < end for a,b in spans)):
                    matches.append(start)
            if len(matches)>1:
                raise ValueError('journal_text_ambiguous')
            if matches:
                start = matches[0];spans.add((start,start+len(body)))
                owned_before[rid] = location(relative,before,start,body)
        ordered = sorted(spans)
        if any(a[1]>b[0] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('journal_text_ambiguous')
        # A generated heading may since have acquired handwritten paragraphs.
        # Keep that heading when it still names surviving manual text.
        protected = []
        headings = list(prose.headings(before))
        for start,end in ordered:
            heading = re.match(r'#### [^\n]+\n\n',before[start:end])
            if heading:
                limit = next((a for a,_,n,_ in headings if a >= end and n <= 4),len(before))
                bounds = prose.section(before)
                if bounds and bounds[0] <= start < bounds[1]:
                    limit = min(limit,bounds[1])
                remainder = before[end:limit]
                for a,b in reversed(ordered):
                    if end <= a < limit:
                        remainder = remainder[:a-end]+remainder[min(b,limit)-end:]
                if remainder.strip():
                    start += len(heading[0])
            protected.append((start,end))
        for start,end in reversed(protected):
            text = text[:start]+text[end:]
        if ordered:
            text = prose.clean(text)
        unique = list(dict.fromkeys(body for _,body in desired))
        positions = {}
        if unique and editor:
            text, positions = editor.arrange(text, desired)
        elif unique:
            group = '\n'.join(body for body in unique)
            text = prose.insert(text,group)
            bounds = prose.subsection(text)
            start = text.rfind(group,bounds[0],bounds[1])
            if start < 0:
                raise ValueError('journal_projection_missing')
            for body in unique:
                positions[body] = (start, body)
                start += len(body)+1
        owned_after = {}
        for rid in involved:
            r = records[rid];target = str(Path(daily)/(r['day']+'.md'))
            receipt = receipts.setdefault(rid,dict(revision=r['revision'],path=target,
                projection=VERSION,present=projected(r),locations=[]))
            if editor:
                receipt['layout'] = editor.version
            if target == relative and projected(r):
                start, body = positions[rid] if editor else positions[prose.block(r)]
                loc = location(relative,text,start,body)
                receipt['locations'].append(loc);owned_after[rid] = loc
        files.append(dict(path=path,relative=relative,before=raw,after=text,
                          owned_before=owned_before,owned_after=owned_after))
    return [f for f in files if f['before'] != f['after'].encode()], list(receipts.items())


def seal(files, changes, root):
    """Activity projections may change the final file hash after prose planning."""
    by_path = {f['path'].relative_to(root).as_posix():f for f in files}
    for rid,receipt in changes:
        for loc in receipt.get('locations',[]):
            f = by_path.get(loc['path'])
            if f:
                start,end = locate(f['after'],loc)
                loc.update(start=start,file_hash=digest(f['after']))
                f['owned_after'] = {**f.get('owned_after',{}),rid:loc}


def pending(state, files, changes, activity_changes, root):
    before = copy.deepcopy(state['applied'])
    for f in files:
        for rid,loc in f.get('owned_before',{}).items():
            receipt = before.setdefault(rid,dict(revision=0,projection=0,path=loc['path'],present=True))
            locs = receipt.setdefault('locations',[])
            receipt['locations'] = [v for v in locs if v['path'] != loc['path']] + [loc]
    return dict(files={f['path'].relative_to(root).as_posix():dict(before=hashlib.sha256(f['before']).hexdigest(),after=digest(f['after'])) for f in files},
                before=before,after=dict(changes),activity=activity_changes)


def recover(state, root):
    from .life_sync import safe_target
    stage = state.get('pending_projection')
    if not stage:
        return False
    states = {}
    for relative,hashes in stage['files'].items():
        path = safe_target(root,relative)
        actual = hashlib.sha256(path.read_bytes() if path.exists() else b'').hexdigest()
        if actual == hashes['after']:
            states[relative] = 'after'
        elif actual == hashes['before']:
            states[relative] = 'before'
        else:
            raise ValueError('journal_interrupted_file_edited')
    for rid,after in stage['after'].items():
        if all(value == 'after' for value in states.values()):
            state['applied'][rid] = after
            continue
        prior = stage['before'].get(rid,{})
        locs = [loc for loc in prior.get('locations',[]) if states.get(loc['path']) != 'after']
        locs += [loc for loc in after.get('locations',[]) if states.get(loc['path']) == 'after']
        value = copy.deepcopy(after)
        value.update(revision=0,projection=0,present=bool(locs),locations=locs)
        state['applied'][rid] = value
    for day,receipt in stage['activity'].items():
        if any(Path(relative).stem == day and status == 'after' for relative,status in states.items()):
            state.setdefault('activity_applied',{})[day] = receipt
    state.pop('pending_projection')
    return True

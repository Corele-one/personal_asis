"""Deterministic learning history from dated owner logs, never file timestamps.

Both the Mac preview and the PWA consume this parser. The PWA reads the existing
origin-owned shared notes replica; it does not create AstrBot messages or habits.
"""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time

LABELS = {'legacy': '历史打卡', 'task': '任务勾选', 'work': '研究日志'}
ROOTS = {'life': 'Calendar/Journal/Daily', 'study': 'Research/Journal'}
ALIASES = (
    ('模拟集成电路', r'模集|模拟集成'), ('模拟电路', r'Analog|模电|运放|三要素'),
    ('FPGA', r'FPGA|DDS'),
    ('信号与系统', r'Signal|信号|拉普拉斯|傅里叶|Bode'),
    ('数字集成电路', r'数集|数字集成'), ('数字电路', r'数电|数字电路|开关代数|组合逻辑'),
    ('微处理器与嵌入式', r'微嵌|微处理器|嵌入式'), ('微电子学', r'微电子学'),
    ('DDCA', r'DDCA'), ('HDL', r'HDL(?:-?Bits)?|Verilog'),
    ('Missing Semester', r'Missing|Vim'), ('C++', r'C\+\+'),
    ('NPU／Attention研究', r'NPU|SCNA|HVX|SCOPE|Attention|llm|量化|Transformer|infra'),
    ('CMake', r'CMake'), ('学术工具', r'Zotero'), ('专业写作', r'专业写作'),
    ('生命教育', r'生命教育'), ('马克思主义原理', r'马原'),
    ('科研', r'Research|科研|论文'), ('工艺', r'工艺作业'),
)
UNFINISHED = re.compile(r'没(?:有)?(?:完成|整理完|学)|未完成|约等于没|等上课|有时间的话|来不及|❌|打印|申请|奖学金|补交|交.{0,8}(?:材料|报告)|答辩|^明天')


def valid_day(value):
    try:
        return bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def eligible(source, locator):
    p = PurePosixPath(locator)
    return (source in ROOTS and str(p.parent) == ROOTS[source] and p.suffix == '.md'
            and valid_day(p.stem))


def canonical_topic(value):
    # An exact known tag can be normalized. Free text uses the first concrete
    # course it names; original wording remains available in content.
    for topic, pattern in ALIASES:
        if re.search(pattern, value, re.I):
            return topic
    return None


def surfaces(text):
    fence = None
    frontmatter = text.startswith('---\n') or text.startswith('---\r\n')
    for number, line in enumerate(text.replace('\r', '').splitlines(), 1):
        if frontmatter:
            if number > 1 and line in ('---', '...'):
                frontmatter = False
            yield number, line, False
            continue
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)$', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            yield number, line, False
        else:
            yield number, line, fence is None


def record(source, locator, day, topic, phase, content, line):
    value = dict(source=source, path=locator, day=day, topic=topic, phase=phase,
                 content=content.strip(), line=line, time='')
    value['id'] = hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return value


def parse_document(text, source, locator):
    if not eligible(source, locator):
        return []
    day = PurePosixPath(locator).stem
    rows = []
    section = None
    work = []
    work_line = 0
    for number, line, visible in surfaces(text):
        if not visible:
            continue
        heading = re.match(r'^(#{1,6})\s+(.+?)\s*$', line)
        if heading:
            name = heading[2].strip()
            if source == 'study':
                # Only the deliberately authored work section, never ToDo,
                # Tomorrow Plan, Prompt, copied reports or file creation dates.
                if len(heading[1]) == 1:
                    if section == 'work':
                        break
                    if re.fullmatch(r'Today[’‘\x27]?s Work|今日工作|今日学习', name, re.I):
                        section, work_line = 'work', number + 1
            else:
                if re.fullmatch(r'(?:📖\s*)?(?:Learning|Study)', name, re.I):
                    section = 'learning'
                elif re.fullmatch(r'(?:🧾\s*)?(?:Task|Tasks|任务)', name, re.I):
                    section = 'tasks'
                elif section is not None:
                    section = None
            continue
        if source == 'study':
            if section == 'work' and not line.lstrip().startswith(('>', '![[', '<!--', '- [ ]')):
                work.append(line)
            continue
        if re.match(r'^---(?:\s+end-(?:multi-)?column(?: ---)?)?\s*$', line) or line.startswith('![['):
            section = None
        if section == 'learning':
            inline = re.match(r'^\s*-\s*\[([^\]\n:]{1,80})::\s*(\d+(?:\.\d+)?)\s*\](.*)$', line)
            checked = re.match(r'^\s*-\s*\[[xX]\]\s+(.+)$', line)
            if inline and float(inline[2]) > 0:
                topic = canonical_topic(inline[1]) or inline[1].strip()
                rows.append(record(source, locator, day, topic, 'legacy', line.strip(), number))
            elif checked:
                topic = canonical_topic(checked[1]) or checked[1].strip()
                rows.append(record(source, locator, day, topic, 'legacy', line.strip(), number))
        elif section == 'tasks':
            checked = re.match(r'^\s*-\s*\[[xX]\]\s+(.+)$', line)
            if checked and not UNFINISHED.search(checked[1]):
                topic = canonical_topic(checked[1])
                if topic:
                    rows.append(record(source, locator, day, topic, 'task', line.strip(), number))
    content = '\n'.join(work).strip()
    if source == 'study' and content and re.search(r'[\w\u4e00-\u9fff]', re.sub(r'!?\[\[.*?\]\]', '', content)):
        # A work log records what was written that day, without asserting that
        # every imperative in it was completed or estimating study time.
        rows.append(record(source, locator, day, canonical_topic(content) or '科研', 'work', content, work_line))
    return rows


def summarize(rows):
    return dict(records=len(rows), days=len({r['day'] for r in rows}),
                topics=len({r['topic'] for r in rows}), sources=dict(Counter(r['source'] for r in rows)),
                kinds=dict(Counter(r['phase'] for r in rows)),
                first=min((r['day'] for r in rows), default=None), last=max((r['day'] for r in rows), default=None))


def scan(config):
    rows, files, unavailable = [], [], []
    for source in config.sources:
        if source.id not in ROOTS or not source.index:
            continue
        folder = source.root / ROOTS[source.id]
        if not folder.is_dir() or source.root.is_symlink() or folder.is_symlink():
            unavailable.append(source.id)
            continue
        for p in sorted(folder.glob('*.md')):
            relative = p.relative_to(source.root).as_posix()
            if (not eligible(source.id, relative) or source.excludes(relative)
                    or any(parent.is_symlink() for parent in (p, *p.parents))):
                continue
            raw = p.read_bytes()
            rows.extend(parse_document(raw.decode('utf-8'), source.id, relative))
            files.append(dict(source=source.id, path=relative, hash=hashlib.sha256(raw).hexdigest()))
    return dict(version=1, rows=sorted(rows, key=lambda r:(r['day'],r['source'],r['line']), reverse=True),
                summary=summarize(rows), files=files, unavailable=unavailable)


def from_shared(home):
    """Read selected complete note copies; withdrawal immediately removes history."""
    path = Path(home) / 'shared.sqlite3'
    if not path.is_file() or path.is_symlink():
        return dict(rows=[], summary=summarize([]), available=False, incomplete=0, checked_at=None)
    groups = defaultdict(list)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        db.execute('BEGIN')
        for (raw,) in db.execute("SELECT body FROM objects WHERE origin='mac' AND collection='notes' AND body IS NOT NULL"):
            body = json.loads(raw)
            if (eligible(body['source'], body['locator'])
                    and (body['expires_at'] is None or body['expires_at'] > time.time())):
                groups[body['source'], body['locator']].append(body)
        meta = dict(db.execute("SELECT key,value FROM meta WHERE key IN ('mac_last_received','mac_snapshot')"))
    rows, incomplete = [], 0
    for (source, locator), parts in groups.items():
        parts.sort(key=lambda p:p['part'])
        text = ''.join(p['text'] for p in parts)
        if (len(parts) != parts[0]['parts'] or [p['part'] for p in parts] != list(range(1,len(parts)+1))
                or len({p['hash'] for p in parts}) != 1
                or hashlib.sha256(text.encode()).hexdigest() != parts[0]['hash']):
            incomplete += 1
            continue
        rows.extend(parse_document(text, source, locator))
    rows.sort(key=lambda r:(r['day'],r['source'],r['line']), reverse=True)
    return dict(rows=rows, summary=summarize(rows), available=True, incomplete=incomplete,
                checked_at=json.loads(meta['mac_last_received']) if 'mac_last_received' in meta else None,
                replica_complete=json.loads(meta.get('mac_snapshot','{}')).get('complete',False))

"""Select personal prose and place it inside the existing Freewrite section."""
import re


TITLE = '#### 聊天随记'
LEGACY = r'## (?:随手记|AstrBot 同步)[ \t]*'


def content(record):
    # Historical captures sometimes include the command prefix. The VPS original
    # remains intact; only the diary presentation loses this transport syntax.
    return re.sub(r'^\s*/?life(?:\s+|$)', '', record['text'], count=1, flags=re.I).strip().replace('\r', '')


def omission(record):
    """Return a narrow, inspectable reason; never infer worth from text length."""
    if record['deleted']:
        return 'deleted'
    if sleep_only(record):
        return 'sleep'
    if record['kind'] == 'task':
        return 'reminder'
    text = content(record)
    bare = text.strip(' \t\n，。！？,.!？~～😊👋🙏')
    if not bare or re.fullmatch(
            r'(?:你好[呀啊]?|您好|hello|hi|嗨|在吗|早安|早上好|晚上好|谢谢[你您]?|多谢|好[的哒]?|嗯+|收到|ok|测试|test)', bare, re.I):
        return 'chat'
    if re.fullmatch(r'(?:status|list|context|forget-context|sleep(?:\s+(?:on|off))?|goodnight|delete(?:\s+[a-f0-9]{64})?)', bare, re.I):
        return 'command'
    if re.fullmatch(r'(?:开启|关闭|暂停|恢复|停止)(?:睡觉|催睡|习惯|学习)?(?:提醒|简报|回顾)', bare):
        return 'command'
    # Standalone date/time answers are context for a task, not diary entries.
    if re.fullmatch(r'(?:(?:\d{4}[-年/])?\d{1,2}[-月/]\d{1,2}日?|今天|明天|后天|今晚)?'
                    r'(?:上午|下午|晚上|早上|早晨|凌晨|中午)?'
                    r'(?:\d{1,2}(?::\d{2}|[点时](?:半|\d{1,2}分?)?))?', bare):
        return 'time'
    if re.match(r'^(?:请|麻烦|记得|帮我)?'
                r'[\d零〇一二三四五六七八九十两年月日号今明后天晚上下午早晨凌点时分半:：\-\s]{0,32}'
                r'(?:请|麻烦|记得|帮我)?(?:提醒我|提醒一下我|设置.{0,12}提醒)', bare):
        return 'reminder'
    # A structured-only update already appears in Habits/Learning. Do not copy
    # it a second time to Freewrite; preserve any additional reflective prose.
    remainder = text
    evidence = [item['evidence'] for name in ('habits', 'learning')
                for item in record.get('tracking', {}).get(name, [])]
    for item in sorted(evidence, key=len, reverse=True):
        remainder = remainder.replace(item, '')
    if evidence and not remainder.strip(' \t\n，。！,.!、；;'):
        return 'activity'
    return None


def sleep_only(record):
    if record['kind'] in ('sleep_bed', 'sleep_wake'):
        return True
    if record['kind'] != 'journal':
        return False
    from .life_bedtime import is_goodnight
    text = content(record)
    return is_goodnight(text) or bool(re.fullmatch(
        r'\s*(?:我(?:刚)?(?:起床|睡醒|醒)了|(?:刚)?(?:起床|睡醒)了)[。！!\s]*', text))


def block(record):
    # Plain prose must not forge another managed block or escape its H4 section.
    # Markdown escapes preserve the visible text while keeping identity comments
    # and heading structure under the sync's control.
    lines, fence = [], None
    for line in content(record).split('\n'):
        if re.match(r'^<!--\s*(?:astrbot:|asis-)', line):
            line = '\\' + line
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif fence is None and (re.match(r'^#{1,4}[ \t]', line) or re.fullmatch(r'(?:=+|-+)[ \t]*', line)):
            line = '\\' + line
        lines.append(line)
    if fence:
        # An unfinished snippet must not swallow the rest of the daily template.
        lines.append(fence)
    text = '\n'.join(lines)
    return text + '\n'


def surface_lines(text):
    """Yield offsets and lines outside fenced examples."""
    fence = None
    offset = 0
    for line in text.splitlines(True):
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})(.*)', line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
        elif fence is None:
            yield offset, line
        offset += len(line)


def headings(text):
    """Locate real Markdown headings; fenced examples do not divide a diary."""
    for offset, line in surface_lines(text):
        match = re.match(r'^(#{1,6})[ \t]+(.+?)[ \t]*\r?\n?$', line)
        if match:
            yield offset, offset + len(line.rstrip('\r\n')), len(match[1]), match[2]


def footer_position(text, start=0, end=None):
    end = len(text) if end is None else end
    return next((offset for offset, line in surface_lines(text)
                 if start <= offset < end and re.fullmatch(r'!\[\[On This Day\.base\]\][ \t]*\n?', line)), end)


def section(text):
    all_headings = list(headings(text))
    matches = [h for h in all_headings if h[2] == 3 and re.fullmatch(r'(?:📕\s*)?Freewrite', h[3], re.I)]
    if len(matches) > 1:
        raise ValueError('ambiguous_freewrite_section')
    if not matches:
        return None
    start = matches[0][1]
    end = next((h[0] for h in all_headings if h[0] > start and h[2] <= 3), len(text))
    end = footer_position(text, start, end)
    # The daily template starts its cards after the Freewrite horizontal rule.
    # Column settings are fenced, but their outer container is not a heading.
    separator = next((offset for offset,line in surface_lines(text)
                      if start <= offset < end and re.fullmatch(r'[ \t]{0,3}---[ \t]*\r?\n?',line)), None)
    if separator is not None:
        end = separator
    return start, end


def subsection(text):
    bounds = section(text)
    if bounds is None:
        return None
    start, end = bounds
    matches = [h for h in headings(text) if start <= h[0] < end and h[2] == 4 and h[3] == '聊天随记']
    if len(matches) > 1:
        raise ValueError('ambiguous_freewrite_section')
    if not matches:
        return None
    start = matches[0][1]
    end = next((h[0] for h in headings(text) if start < h[0] < end and h[2] <= 4), end)
    return start, end


def insert(text, rendered):
    bounds = section(text)
    if bounds is None:
        # Keep an existing daily footer (e.g. On This Day) outside Freewrite.
        pos = footer_position(text)
        text = splice(text, pos, '### 📕Freewrite\n')
        bounds = section(text)
    managed = subsection(text)
    if managed is None:
        text = splice(text, bounds[1], TITLE + '\n')
        managed = subsection(text)
    return splice(text, managed[1], rendered)


def splice(text, pos, addition):
    # Add separators without stripping or rewriting any existing template bytes.
    prefix, suffix = text[:pos], text[pos:]
    prefix = prefix.rstrip('\r\n')
    return ((prefix + '\n\n') if prefix else '') + addition.rstrip('\r\n') + ('\n\n' if suffix else '\n') + suffix


def clean(text):
    # Never remove the template Freewrite heading or an occupied/manual section.
    found = list(headings(text));remove = []
    for start,end,level,label in found:
        if not ((level == 4 and label == '聊天随记') or (level == 2 and label in ('随手记','AstrBot 同步'))):
            continue
        limit = next((a for a,_,n,_ in found if a > end and n <= level),len(text))
        if level == 4:
            limit = min(limit,next((offset for offset,line in surface_lines(text)
                if end < offset < limit and re.fullmatch(r'[ \t]{0,3}---[ \t]*\r?\n?',line)),limit))
        if not text[end:limit].strip():
            remove.append((start,limit))
    for start,end in reversed(remove):
        text = text[:start]+text[end:]
    return text

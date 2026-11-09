"""An explicit journal entry is different from a conversation or a system action."""
import re

SOURCES = ('life_command', 'conversation', 'bedtime', 'reminder', 'focus')
MANAGEMENT = {'status','list','context','forget-context','sleep','goodnight','delete','progress','proactive'}


def entry_content(text):
    match = re.fullmatch(r'/?life\s+([\s\S]+)', text.strip())
    if not match or match[1].split()[0] in MANAGEMENT:
        return None
    return match[1].strip() or None


def source(record):
    value = record.get('capture_source')
    if value is not None:
        if value not in SOURCES:
            raise ValueError('invalid_capture_source')
        return value
    # Old plain captures have no proof of recording intent. Never upgrade them
    # merely because an earlier model assigned a diary kind or habit.
    if entry_content(record['text']) is not None:
        return 'life_command'
    if record['kind'] in ('sleep_bed','sleep_wake'):
        return 'bedtime'
    if record['kind'] == 'task' and record.get('due_at'):
        return 'reminder'
    if re.search(r'帮我持续跟进|帮我持续关注|帮我关注|我的目标是', record['text']):
        return 'focus'
    return 'conversation'


def is_entry(record):
    return source(record) == 'life_command' and not record.get('entry_excluded', False)


def visible(record):
    return source(record) != 'conversation' and not record.get('entry_excluded', False)


def sync_record(record):
    """Keep conversation memory available, explicitly distinct from journal intent."""
    from .life_tracking import observations
    value = dict(record, capture_source=source(record))
    value['tracking'] = observations(record)
    return value


def reminder_request(text):
    """Only an unquoted direct request can expose the reminder writer."""
    text = re.sub(r'```[\s\S]*?```|`[^`]*`|<system_reminder>[\s\S]*?</system_reminder>', '', text)
    text = re.sub(r'“[^”]*”|「[^」]*」|"[^"\n]*"|‘[^’]*’', '', text)
    text = '\n'.join(line for line in text.splitlines() if not line.lstrip().startswith('>')).strip()
    # Preserve natural phrasing ("我明天有课，提醒我…", "过十分钟提醒我…").
    # Removing quoted/negated clauses must not turn a discussion into a request.
    text = re.sub(r'(?:不要|别|不需要|不用)(?:再)?提醒(?:一下)?我[^，。！？;；\n]*', '', text)
    return bool(re.search(r'提醒我|提醒一下我|设置.{0,12}提醒', text))

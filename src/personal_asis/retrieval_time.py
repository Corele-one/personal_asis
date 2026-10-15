"""Explicit note dates and bounded question time ranges; never substitute mtime."""
from datetime import date,datetime,timedelta
from pathlib import PurePosixPath
import re
from zoneinfo import ZoneInfo


def _date(value):
    try:return date.fromisoformat(value)
    except (ValueError,TypeError):return None


def note_date(path, text):
    values=[]
    name=PurePosixPath(path).name
    match=re.search(r'(?<!\d)(20\d{2})[-_年](\d{1,2})[-_月](\d{1,2})(?!\d)',name)
    if match:
        value=_date(f'{match[1]}-{int(match[2]):02}-{int(match[3]):02}')
        if value:values.append((value,'filename'))
    lines=text.splitlines()
    if lines and lines[0].strip()=='---':
        for line in lines[1:]:
            if line.strip() in ('---','...'):break
            match=re.match(r'\s*(date|created|created_at)\s*:\s*[\"\']?(20\d{2}-\d{2}-\d{2})(?=[T\s\"\']|$)',line)
            if match:
                value=_date(match[2])
                if value:values.append((value,'frontmatter:'+match[1]))
    if len({v for v,_ in values})>1:return None,'conflicting_note_dates'
    return (values[0][0].isoformat(),values[0][1]) if values else (None,'unknown')


def question_window(query, today=None):
    today=today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    days=None;assumed=False;months=False
    numbers={'一':1,'两':2,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10}
    match=re.search(r'(?:最近|近|过去)\s*(\d{1,3}|[一两二三四五六七八九十])\s*(天|周|星期|个月|月)',query)
    if match:
        count=int(match[1]) if match[1].isdigit() else numbers[match[1]]
        months=match[2] in ('个月','月')
        days=count*({'天':1,'周':7,'星期':7,'个月':30,'月':30}[match[2]])
    elif '今天' in query:days=1
    elif '昨天' in query:
        value=(today-timedelta(days=1)).isoformat()
        return {'start':value,'end':value,'basis':'question','unknown_dates':'excluded'}
    elif '本周' in query:days=today.weekday()+1
    elif '本月' in query:days=today.day
    elif '上个月' in query:
        end=today.replace(day=1)-timedelta(days=1)
        return {'start':end.replace(day=1).isoformat(),'end':end.isoformat(),'basis':'question','unknown_dates':'excluded'}
    elif '最近' in query and re.search(r'记录|日记|笔记|复盘|近况',query):
        days=30;assumed=True
    if days is None or not 1<=days<=3660:return None
    return {'start':(today-timedelta(days=days-1)).isoformat(),'end':today.isoformat(),
            'basis':'recent_defaults_to_30_days' if assumed else 'question_months_as_30_days' if months else 'question','unknown_dates':'excluded'}


def in_window(value,window):
    if window is None:return True
    if (not isinstance(window,dict) or set(window)!={'start','end','basis','unknown_dates'}
            or not _date(window['start']) or not _date(window['end']) or window['start']>window['end']):
        raise ValueError('invalid_retrieval_time_window')
    return value is not None and window['start']<=value<=window['end']

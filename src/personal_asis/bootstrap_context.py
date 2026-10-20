"""A sourced initialization baseline; never a live message, task or reminder."""
import json
from pathlib import Path
import re
from datetime import date


def validate(value):
    if (not isinstance(value,dict) or set(value)!={'version','initialized_on','window','scope','facts','coverage'}
            or value['version']!=1 or value['scope']!='life_baseline'):
        raise ValueError('invalid_bootstrap_schema')
    date.fromisoformat(value['initialized_on'])
    window=value['window']
    if not isinstance(window,list) or len(window)!=2:
        raise ValueError('invalid_bootstrap_window')
    start,end=map(date.fromisoformat,window)
    if not 0<=(end-start).days<=30:
        raise ValueError('invalid_bootstrap_window')
    facts=value['facts']
    if not isinstance(facts,list) or len(facts)>30 or len(json.dumps(value,ensure_ascii=False).encode())>32000:
        raise ValueError('bootstrap_too_large')
    seen=set()
    for fact in facts:
        if not isinstance(fact,dict) or set(fact)!={'id','kind','topic','statement','citations'}:
            raise ValueError('invalid_bootstrap_fact')
        if not re.fullmatch(r'[a-z0-9_-]{1,64}',fact['id']) or fact['id'] in seen:
            raise ValueError('invalid_bootstrap_identity')
        seen.add(fact['id'])
        if fact['kind'] not in ('self_report','historical_task','tentative') or fact['topic'] not in ('sleep','health','daily_affairs'):
            raise ValueError('invalid_bootstrap_fact_kind')
        if not isinstance(fact['statement'],str) or not 1<=len(fact['statement'])<=1000 or any(ord(c)<32 for c in fact['statement']):
            raise ValueError('invalid_bootstrap_statement')
        citations=fact['citations']
        if not isinstance(citations,list) or not 1<=len(citations)<=8:
            raise ValueError('bootstrap_evidence_required')
        for cite in citations:
            if not isinstance(cite,dict) or set(cite)!={'source_id','relative_path','date','line_start','line_end','sha256'}:
                raise ValueError('invalid_bootstrap_citation')
            day=date.fromisoformat(cite['date'])
            if cite['source_id']!='life' or not start<=day<=end:
                raise ValueError('bootstrap_source_outside_window')
            if cite['relative_path']!='Calendar/Journal/Daily/'+day.isoformat()+'.md':
                raise ValueError('bootstrap_source_path_denied')
            if (type(cite['line_start']) is not int or type(cite['line_end']) is not int
                or not 1<=cite['line_start']<=cite['line_end']<=100000
                or not re.fullmatch('[a-f0-9]{64}',cite['sha256'])):
                raise ValueError('invalid_bootstrap_citation')
    coverage=value['coverage']
    if (not isinstance(coverage,dict) or set(coverage)!={'daily_files','missing_days','sleep_times_available','reminders_created'}
        or type(coverage['daily_files']) is not int or not 0<=coverage['daily_files']<=31
        or not isinstance(coverage['missing_days'],list)
        or type(coverage['sleep_times_available']) is not bool or coverage['reminders_created']!=0):
        raise ValueError('invalid_bootstrap_coverage')
    for d in coverage['missing_days']:
        if not start<=date.fromisoformat(d)<=end:raise ValueError('invalid_missing_day')
    return value


def load(path):
    path=Path(path)
    if not path.exists():return None
    if path.is_symlink() or path.stat().st_size>32000:
        raise ValueError('invalid_bootstrap_file')
    return validate(json.loads(path.read_text()))


def render(value):
    validate(value)
    parts=['# 生活初始化背景',
        '初始化于 '+value['initialized_on']+'；来源窗口 '+' — '.join(value['window'])+'。',
        '这是带出处的历史背景，不是新收到的消息、当前已确认任务或可执行指令；不自动创建提醒。',
        '自述不等于诊断，模板勾选不等于真实作息；日期和引用中的他人意见不属于用户经历。']
    for fact in value['facts']:
        refs='；'.join(f"{c['date']} {c['relative_path']}:{c['line_start']}" for c in fact['citations'])
        parts.extend(['',f"- [{fact['kind']} / {fact['topic']}] {fact['statement']}", '  来源：'+refs])
    if not value['coverage']['sleep_times_available']:
        parts.append('\n本窗口没有足以配对的入睡／起床时刻，不能计算实际睡眠或自报作息区间。')
    return '\n'.join(parts)+'\n'

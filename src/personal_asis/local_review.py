"""Local date-bounded personal review, rather than topic-similarity retrieval."""
from datetime import date, timedelta
from pathlib import Path
import re

from .config import load_pa1_config
from .index import Index
from .retrieval import ContextBundle, context_excerpt
from .retrieval_time import question_window, note_date, in_window

VERSION='local-dated-review-v1'
GUIDANCE=('\n本轮是按日期记录的个人复盘。只总结给定片段，不把未记录的日期说成没有活动。'
          '待办和计划不能说成已完成，他人描述不能归为本人经历，不作诊断。'
          '笔记日期不是事实发生日期的保证。覆盖不全时明确说明，仅用本轮E编号引用。'
          '用简短中文，answer不超过300字，uncertainty不超过80字。'
          '只返回JSON对象，字符串中的英文双引号必须转义。')


def plan(query, sources, mode, today=None):
    if (mode not in ('auto','life') or not re.search(r'总结|复盘|回顾|做了什么|做了哪些',query)
            or not re.search(r'我|本人|生活|日记',query)):
        return None
    # Broaden only this explicit local workflow; old paid sessions retain their parser.
    normalized=re.sub(r'(最近|近|过去)\s*的\s*',r'\1',query)
    window=question_window(normalized,today)
    if window is None and re.search(r'上(?:一)?周',query):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        current=today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
        end=current-timedelta(days=current.weekday()+1)
        window={'start':(end-timedelta(days=6)).isoformat(),'end':end.isoformat(),
                'basis':'previous_calendar_week','unknown_dates':'excluded'}
    if window is None:return None
    selected=['life'] if 'life' in sources else list(sources)
    return {'version':VERSION,'window':window,'sources':selected}


def validate(value, sources):
    if (not isinstance(value,dict) or set(value)!={'version','window','sources'}
            or value['version']!=VERSION or not isinstance(value['sources'],list) or not value['sources']
            or not set(value['sources'])<=set(sources)):
        raise ValueError('local_review_invalid_plan')
    in_window(None,value['window'])


def build(home, query, value):
    validate(value,value['sources'])
    candidates=[];records=set();dates=set()
    with Index(Path(home)/'index.sqlite3',load_pa1_config(Path(home))) as index:
        sources={s.id:s for s in index.config.sources}
        rows=index.db.execute('''SELECT d.* FROM documents d JOIN sources s ON s.id=d.source_id
            WHERE d.active=1 AND s.enabled=1 AND s.available=1 ORDER BY d.document_id''').fetchall()
        for row in rows:
            if row['source_id'] not in value['sources']:continue
            source=sources[row['source_id']]
            if source.reading_cache or not source.allows_model('mimo',row['policy']=='private',row['path']):continue
            filename_date,_=note_date(row['path'],'')
            if filename_date and not in_window(filename_date,value['window']):continue
            current=index._current(row)
            if current is None:continue
            source,path,text,private=current
            if not source.allows_model('mimo',private,row['path']):continue
            recorded,basis=note_date(row['path'],text)
            if not in_window(recorded,value['window']):continue
            records.add(row['document_id']);dates.add(recorded)
            # Existing ContextBundle validation accepts exact single-line excerpts.
            start=context_excerpt(text,'')['line_start']-1
            lines=text.splitlines();body=[]
            for i in range(start,len(lines)):
                line=lines[i]
                if (not line.strip() or re.match(r'^\s*(#{1,6}\s|```|~~~|\|?[- :|]+$)',line)
                        or re.fullmatch(r'\s*[-*]\s*\[ \]\s*',line)):continue
                body.append((i,line))
            # Prefer substantive paragraphs. Select across dates before extra passages.
            for rank,(i,line) in enumerate(sorted(body,key=lambda item:(-len(item[1]),item[0]))[:3]):
                e={'document_id':row['document_id'],'content_hash':row['content_hash'],
                   'node_id':index.config.node_id,'source_id':source.id,'path_hint':row['path'],
                   'title':row['title'][:120],'index_version':row['index_version'],'original_uri':path.as_uri(),
                   'line_start':i+1,'line_end':i+1,'column_start':1,'excerpt':line[:240],
                   'sensitivity':'private' if private else 'normal','record_date':recorded,'record_date_basis':basis}
                candidates.append((rank,recorded,row['document_id'],i,e))
    evidence=[]
    max_chars=160 if len(dates)>5 else 240
    for *_,e in sorted(candidates,key=lambda item:item[:4]):
        e={**e,'excerpt':e['excerpt'][:max_chars]}
        trial=ContextBundle(query,'mimo',evidence+[e],'dated_review')
        import json
        if len(json.dumps(trial.cloud_input(),ensure_ascii=False).encode())>5400:continue
        evidence.append(e)
        if len(evidence)==7:break
    selected_dates=sorted({e['record_date'] for e in evidence})
    coverage={'window':value['window'],'eligible_records':len(records),'recorded_dates':sorted(dates),
              'selected_records':len({e['document_id'] for e in evidence}),'selected_dates':selected_dates,
              'selected_passages':len(evidence),'partial_excerpts':True,
              'all_recorded_dates_represented':set(selected_dates)==dates,
              'dates_without_records_mean_no_activity':False}
    bundle=ContextBundle(query,'mimo',evidence,'dated_review',None if evidence else 'no_dated_records')
    bundle.revalidate(home)
    return bundle,coverage


def coverage_text(coverage):
    w=coverage['window']
    return ('复盘范围：'+w['start']+' 至 '+w['end']+'；找到'+str(len(coverage['recorded_dates']))+
            '个日期的获准记录，本次选用'+str(len(coverage['selected_dates']))+'个日期的片段。'
            '没有记录的日期不代表没有活动；这不是该时段的完整活动清单。')

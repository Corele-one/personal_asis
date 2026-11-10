#!/usr/bin/env python3
"""Persistent, single-attempt synthetic acceptance. Never imports owner history."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request,urlopen

ROOT=Path('/home/mac/.local/share/personal-asis-memory-acceptance')
TOKENS=json.loads((ROOT/'clients.json').read_text())
STATE=ROOT/'results.json'
results=json.loads(STATE.read_text()) if STATE.exists() else {}


def save():
    temporary=STATE.with_suffix('.next');temporary.write_text(json.dumps(results,ensure_ascii=False));temporary.chmod(0o600);temporary.replace(STATE)


def call(action,args=None,client='acceptance-admin',token=None):
    request=Request('http://127.0.0.1:23101/v1/memory',method='POST',
        data=json.dumps(dict(action=action,arguments=args or {}),ensure_ascii=False).encode(),
        headers={'Authorization':'Bearer '+(TOKENS[client] if token is None else token),'Content-Type':'application/json'})
    try:
        with urlopen(request,timeout=90) as response:return response.status,json.load(response)
    except HTTPError as response:
        with response:return response.code,json.load(response)


def step(name,function):
    if name in results:
        old=results[name]
        if old['state']!='passed':raise RuntimeError('prior_step_not_passed_no_automatic_retry:'+name)
        return old['value']
    results[name]=dict(state='sent_or_unknown');save()
    start=time.monotonic()
    try:
        value=function()
        results[name]=dict(state='passed',seconds=round(time.monotonic()-start,3),value=value);save()
        print(json.dumps(dict(step=name,passed=True,seconds=results[name]['seconds'])),flush=True)
        return value
    except BaseException as error:
        results[name].update(state='failed_or_unknown',error_type=type(error).__name__);save()
        print(json.dumps(dict(step=name,passed=False,error_type=type(error).__name__)),flush=True)
        raise


def ok(action,args=None,client='acceptance-admin'):
    status,value=call(action,args,client)
    if status!=200:raise RuntimeError(value.get('error','memory_http_failed'))
    return value


def capture(source,text,client='acceptance-chat',**extra):
    return ok('capture',dict(source_id=source,text=text,synthetic=True,**extra),client)


def semantics(fixture):
    checks={
        'stable_preference':(1,'中文'), 'explicit_decision':(1,'路由'), 'temporary_request':(0,None),
        'negative_preference':(1,None),'quote':(0,None),'assistant_suggestion':(0,None),
        'cancel_plan':(1,None),'correction':(1,'英文'),'different_projects':(2,None),'life_fact':(0,None)}
    for case in json.loads(fixture.read_text())['cases']:
        if case['id'] not in checks:continue
        def run(case=case):
            value=ok('preview',dict(source_id='semantics-v1/'+case['id'],text=case['input'],
                scope_context='project:项目甲' if case['id']=='correction' else 'global',synthetic=True))
            records=value['candidates'];count,word=checks[case['id']]
            assert len(records)==count
            if word:assert any(word in c['text'] for c in records)
            if case['id']=='cancel_plan':assert records[0]['state']=='cancelled' and '完成' not in records[0]['text']
            if case['id']=='negative_preference':assert any(w in records[0]['text'] for w in ['不','避免','拒绝','非表格'])
            if case['id']=='different_projects':assert {c['scope'] for c in records}=={'project:项目甲','project:项目乙'}
            if case['id']=='correction':assert records[0]['scope']=='project:项目甲'
            return dict(count=len(records),kind=[c['kind'] for c in records],scopes=[c['scope'] for c in records],
                states=[c['state'] for c in records],real_extraction=True)
        step('semantics/'+case['id'],run)


def checkpoint(action,path):
    command=['sudo','-n','python3','/opt/personal-asis-memory/current/deploy/memory-checkpoint.py',action,'--checkpoint',path]
    output=subprocess.run(command,capture_output=True,text=True,timeout=110,check=True)
    value=json.loads(output.stdout)
    for _ in range(30):
        try:
            value['status']=ok('status');return value
        except Exception:time.sleep(1)
    raise RuntimeError('memory_service_not_reachable_after_checkpoint')


def crud():
    def auth():
        assert call('status',token='invalid')[0]==401
        request=Request('http://127.0.0.1:23101/v1/memory',method='POST',data=b'{}')
        try:urlopen(request,timeout=5);raise AssertionError()
        except HTTPError as e:assert e.code==401
        assert call('search',dict(query='language',user_id='other-owner'))[0]==409
        assert call('get',dict(memory_id='00000000-0000-0000-0000-000000000001'))[0]==409
        return dict(unauthenticated=True,wrong_token=True,identity_override_denied=True,unknown_id_denied=True)
    step('auth',auth)
    first=step('capture',lambda:capture('crud/initial','以后请用中文解释电路原理。'))['records'][0]
    a=step('project-a',lambda:capture('crud/project-a','项目甲以后统一使用中文文档。',scope_context='project:项目甲'))['records'][0]
    b=step('project-b',lambda:capture('crud/project-b','项目乙以后统一使用英文文档。',scope_context='project:项目乙'))['records'][0]
    def duplicate():
        before=ok('status')['calls']
        value=capture('crud/initial','以后请用中文解释电路原理。')
        assert value['duplicate'] and value['records'][0]['id']==first['id']
        assert ok('status')['calls']==before
        return dict(single_write=True,no_provider_call=True)
    step('duplicate',duplicate)
    def recall():
        value=ok('search',dict(query='讲解电路应选何种语言？'),'acceptance-work')
        assert first['id'] in [x['id'] for x in value['records']]
        item=ok('get',dict(memory_id=first['id']),'acceptance-work')
        assert item['metadata']['quote']=='以后请用中文解释电路原理。'
        found=ok('search',dict(query='项目文档',scope='project:项目甲'),'acceptance-work')['records']
        assert a['id'] in [x['id'] for x in found] and b['id'] not in [x['id'] for x in found]
        return dict(shared_owner_scope=True,semantic_paraphrase=True,provenance=True,project_scopes=True)
    step('recall',recall)
    def temporary():
        assert not capture('crud/temporary','这次只写一句话。')['records']
        assert ok('get',dict(memory_id=first['id']))['version']==1
        return dict(not_globalized=True)
    step('temporary',temporary)
    base='/var/backups/personal-asis-memory-data/m1-base'
    latest='/var/backups/personal-asis-memory-data/m1-corrected'
    step('backup-base',lambda:checkpoint('backup',base))
    def concurrent():
        def correction(pair):
            source,text,client=pair
            return call('capture',dict(source_id=source,text=text,synthetic=True,memory_id=first['id'],expected_version=1),client)
        with ThreadPoolExecutor(max_workers=2) as pool:
            values=list(pool.map(correction,[('crud/correction-a','以后解释电路统一用英文。','acceptance-chat'),
                ('crud/correction-b','以后解释电路统一用中文并配图。','acceptance-work')]))
        assert sorted(v[0] for v in values)==[200,409]
        assert any(v.get('error')=='memory_version_conflict' for _,v in values)
        current=ok('get',dict(memory_id=first['id']))
        assert current['version']==2
        assert not ok('validate',dict(memory_id=first['id'],version=1),'acceptance-work')['valid']
        history=ok('history',dict(memory_id=first['id']))
        assert len(history['history'])>=2 and len(history['sources'])>=2
        return dict(one_success_one_conflict=True,history=True,old_cache_invalid=True)
    step('concurrent',concurrent)
    step('backup-corrected',lambda:checkpoint('backup',latest))
    def restore_old_revision():
        value=checkpoint('restore',base)
        assert not value['status']['consistency_ready']
        assert call('get',dict(memory_id=first['id']))[0]==409
        return dict(stale_backup_refuses_reads=True,calls_not_rolled_back=True)
    step('restore-old-revision',restore_old_revision)
    def restore_latest():
        value=checkpoint('restore',latest)
        assert value['status']['consistency_ready']
        assert ok('get',dict(memory_id=first['id']))['version']==2
        return dict(current_revision_restored=True)
    step('restore-latest',restore_latest)
    def withdraw():
        value=ok('withdraw',dict(memory_id=first['id'],expected_version=2,synthetic=True),'acceptance-work')
        assert value['withdrawn']
        assert not ok('validate',dict(memory_id=first['id'],version=2))['valid']
        assert call('capture',dict(source_id='crud/initial',text='以后请用中文解释电路原理。',synthetic=True),'acceptance-chat')[1]['error']=='memory_source_withdrawn'
        assert call('history',dict(memory_id=first['id']))[0]==409
        return dict(withdrawn=True,old_source_blocked=True,cache_invalid=True)
    step('withdraw',withdraw)
    def restore_old_withdrawn():
        value=checkpoint('restore',latest)
        assert value['status']['consistency_ready']
        assert call('get',dict(memory_id=first['id']))[0]==409
        assert not ok('validate',dict(memory_id=first['id'],version=2))['valid']
        ids=[x['id'] for x in ok('list')['records']]
        assert first['id'] not in ids and a['id'] in ids and b['id'] in ids
        return dict(withdrawn_not_resurrected=True,other_memories_preserved=True)
    step('restore-withdrawn',restore_old_withdrawn)
    step('final-status',lambda:ok('status'))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=['semantics','crud','status'])
    parser.add_argument('--fixture',type=Path);args=parser.parse_args()
    if args.phase=='semantics':semantics(args.fixture)
    elif args.phase=='crud':crud()
    else:print(json.dumps(ok('status')))

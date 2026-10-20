"""Exact, expiring write plans for native Pi's human confirmation UI."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid
from .native_sources import PROFILE, HOME, private_write, xhs_configuration

WUC = {'append_diary': {'content'}, 'update_article_note': {'note_idx','note'},
       'set_article_status': {'note_idx','status'}}
XHS = {'like_feed': {'feed_id','xsec_token','unlike'},
       'favorite_feed': {'feed_id','xsec_token','unfavorite'},
       'post_comment_to_feed': {'feed_id','xsec_token','content'}}


def validate(request):
    if set(request) != {'source','operation','arguments'} or not isinstance(request['arguments'],dict):
        raise ValueError('invalid_write_request')
    allowed = (WUC if request['source']=='wucai' else XHS if request['source']=='xiaohongshu'
               else {'publish_summary': {'title','content'}} if request['source']=='dashboard' else {})
    if request['operation'] not in allowed or set(request['arguments']) != allowed[request['operation']]:
        raise ValueError('write_operation_or_fields_denied')
    for key,value in request['arguments'].items():
        if key in ('unlike','unfavorite'):
            if type(value) is not bool:raise ValueError('write_boolean_required')
        elif not isinstance(value,str) or not value.strip() or len(value.encode())>(300 if request['source']=='dashboard' and key=='title' else 16000) or any(ord(c)<32 and c not in '\n\r\t' for c in value):
            raise ValueError('invalid_write_text')
    if request['operation']=='set_article_status' and request['arguments']['status'] not in ('inbox','later','archive'):
        raise ValueError('invalid_wucai_status')
    return request


def prepare(request, profile=PROFILE):
    request=validate(request)
    for previous in (Path(profile)/'write-plans').glob('*.json'):
        if time.time()-previous.stat().st_mtime > 300:
            previous.unlink(missing_ok=True)
    # Identity is carried separately. The xsec token is a page-access token, not the login cookie.
    canonical=json.dumps(request,ensure_ascii=False,sort_keys=True)
    key=uuid.uuid4().hex
    value=dict(request=request,expires=time.time()+300,digest=hashlib.sha256(canonical.encode()).hexdigest())
    private_write(Path(profile)/'write-plans'/(key+'.json'),json.dumps(value,ensure_ascii=False))
    return dict(plan=key,digest=value['digest'],preview=canonical,expires_in=300)


def execute(plan_id, confirmation, profile=PROFILE, home=HOME):
    import re
    if not re.fullmatch('[0-9a-f]{32}',plan_id):raise ValueError('invalid_write_plan')
    profile=Path(profile)
    path=profile/'write-plans'/(plan_id+'.json')
    value=json.loads(path.read_text())
    if time.time()>value['expires'] or confirmation!=value['digest']:
        raise ValueError('write_confirmation_expired_or_mismatch')
    request=validate(value['request'])
    canonical=json.dumps(request,ensure_ascii=False,sort_keys=True)
    if hashlib.sha256(canonical.encode()).hexdigest()!=confirmation:
        raise ValueError('write_plan_changed')
    db=sqlite3.connect(profile/'write-ledger.sqlite3')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS writes(id TEXT PRIMARY KEY,state TEXT NOT NULL)')
        with db:
            db.execute('INSERT INTO writes VALUES(?,?)',(plan_id,'unknown'))
        # Reservation commits before the network call; a crash/timeout never auto-retries.
        if request['source']=='wucai':
            from .reading_sources import Wucai
            class Writer(Wucai):
                READS=set(WUC)
            result=Writer('cn').call(request['operation'],request['arguments'])
        elif request['source']=='dashboard':
            import subprocess
            # The publication contains only the exact summary approved in the native UI.
            payload=dict(request_id=plan_id,**request['arguments'])
            from .mac_content import validate as validate_publication
            validate_publication(payload)
            response=subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-p','22',
                'mac@35.209.202.207','PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.mac_content'],
                input=json.dumps(payload,ensure_ascii=False),capture_output=True,text=True,timeout=15,check=True)
            result=json.loads(response.stdout)
            if result.get('saved') is not True:raise ValueError('dashboard_publication_unconfirmed')
        else:
            from .social_reading import XiaoHongShu
            endpoint=xhs_configuration(home)
            if not endpoint:raise ValueError('xiaohongshu_mcp_unavailable')
            client=XiaoHongShu(endpoint)
            init=client._rpc('initialize',{'protocolVersion':client.protocol,'capabilities':{},'clientInfo':{'name':'personal-asis-confirmed-write','version':'2'}})
            client.protocol=init['protocolVersion']
            client._rpc('notifications/initialized',{},notification=True)
            listed=client._rpc('tools/list',{})
            if request['operation'] not in {t['name'] for t in listed.get('tools',[])}:
                raise ValueError('xiaohongshu_write_tool_not_installed')
            result=client._rpc('tools/call',{'name':request['operation'],'arguments':request['arguments']})
            if result.get('isError'):raise ValueError('xiaohongshu_write_failed_verify_platform')
        with db:db.execute('UPDATE writes SET state=? WHERE id=?',('succeeded',plan_id))
        path.unlink(missing_ok=True)
        return dict(state='succeeded',result=result)
    finally:
        db.close()


def main():
    import os
    os.umask(0o077)
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','execute'])
    args=parser.parse_args()
    try:
        data=json.loads(sys.stdin.read(128000))
        profile=Path(os.environ.get('PI_CODING_AGENT_DIR',str(PROFILE)))
        home=Path(os.environ.get('ASIS_PERSONAL_HOME',str(HOME)))
        result=prepare(data,profile) if args.action=='prepare' else execute(data['plan'],data['digest'],profile,home)
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except Exception as error:
        # No upstream bodies, credential values or source content in failure output.
        print(json.dumps({'error':type(error).__name__,'state':'not_succeeded_or_unknown_verify_before_retry'}))
        return 1


if __name__=='__main__':
    raise SystemExit(main())

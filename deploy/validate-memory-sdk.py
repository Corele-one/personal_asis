"""Real pinned SDK failure-window tests, synthetic data and fixed provider calls.

Run as asis-memory while the primary authority is stopped, in a separate engine
directory. No second process opens a live Qdrant directory.
"""
import contextlib
import json
import os
from pathlib import Path
import resource
import sqlite3
import time

from personal_asis.memory_authority import MemoryAuthority,MemoryFault
from personal_asis.memory_sdk import Mem0Backend,CallLedger

os.umask(0o077)
home=Path('/var/lib/personal-asis-memory')
receipt=home/'sdk-validation.json'
if receipt.exists():
    print(receipt.read_text());raise SystemExit()
report=dict(state='sent_or_unknown',synthetic_only=True)
receipt.write_text(json.dumps(report))
directory=home/'sdk-validation';directory.mkdir(mode=0o700)
engine=directory/'engine';engine.mkdir(mode=0o700)
cfg=json.loads((home/'config.json').read_text())
ledger=CallLedger(home/'calls.sqlite3')
started=time.monotonic()
extractions=0


def extract(text,context):
    global extractions
    extractions+=1
    return [dict(text=text,quote=text,kind='preference',scope=context,topic='sdk_language',state='active')]


def crash(_):
    raise RuntimeError('synthetic_after_sdk_commit')


def open_authority():
    return MemoryAuthority(directory/'barriers.sqlite3',Mem0Backend(engine,cfg,ledger),extract)


def capture(a,source,text,**extra):
    return a.dispatch('acceptance-chat','capture',dict(source_id=source,text=text,synthetic=True,**extra))


try:
    with open(os.devnull,'w') as quiet,contextlib.redirect_stdout(quiet),contextlib.redirect_stderr(quiet):
        a=open_authority();a.fault=crash
        try:capture(a,'gap-add','合成试验：以后解释电路用中文。');raise AssertionError()
        except MemoryFault as error:assert str(error)=='memory_write_unknown_no_retry'
        a.close();a=open_authority()
        value=capture(a,'gap-add','合成试验：以后解释电路用中文。')
        assert value['duplicate'] and extractions==1 and a.ready
        identifier=value['records'][0]['id']
        report['add_gap_readback_without_reembedding']=True
        foreign=a.backend.add('合成另一身份偏好。','other-synthetic-owner',dict(scope='global',revision=1))
        assert len(a.backend.all('other-synthetic-owner'))==1
        for action in ['get','history']:
            try:a.dispatch('acceptance-work',action,dict(memory_id=foreign));raise AssertionError()
            except MemoryFault as error:assert str(error)=='memory_not_found'
        assert all(x['id']!=foreign for x in a.dispatch('acceptance-work','list',{})['records'])
        a.backend.erase(foreign,'other-synthetic-owner')
        report['real_sdk_foreign_identity_get_history_list_denied']=True
        a.fault=crash
        try:capture(a,'gap-update','合成试验：以后解释电路改用英文。',memory_id=identifier,expected_version=1);raise AssertionError()
        except MemoryFault as error:assert str(error)=='memory_write_unknown_no_retry'
        a.close();a=open_authority()
        value=capture(a,'gap-update','合成试验：以后解释电路改用英文。',memory_id=identifier,expected_version=1)
        assert value['duplicate'] and value['records'][0]['version']==2 and extractions==2
        assert '英文' in value['records'][0]['memory']
        assert len(a.backend.history(identifier))>=2
        report['update_gap_readback_without_reembedding']=True
        a.dispatch('acceptance-work','withdraw',dict(memory_id=identifier,expected_version=2,synthetic=True))
        assert a.backend.get(identifier) is None and a.backend.history(identifier)==[]
        with sqlite3.connect(engine/'history.sqlite3') as db:
            assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
        assert '合成试验：以后解释电路'.encode() not in (directory/'barriers.sqlite3').read_bytes()
        report.update(sdk_history_purged=True,infer_false_message_buffer_empty=True,receipts_no_duplicate_text=True)
        a.close();ledger.close()
    report.update(state='passed',seconds=round(time.monotonic()-started,3),
        peak_rss_mib=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
        real_embedding_calls=3,real_llm_calls=0)
except BaseException as error:
    report.update(state='failed_or_unknown',error_type=type(error).__name__)
receipt.write_text(json.dumps(report));print(json.dumps(report))

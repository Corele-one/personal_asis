"""Purge unusable local PA1 payloads; retain minimal usage/idempotency markers."""

from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from .config import load_pa1_config
from .index import Index


def clean(home, clock=time.time):
    home=Path(home)
    config=load_pa1_config(home)
    current={}
    with Index(home/'index.sqlite3',config) as index:
        for row in index.db.execute('SELECT * FROM documents WHERE active=1').fetchall():
            value=index._current(row)
            if value is not None:
                source,_,_,private=value
                current[row['document_id']]=(row['content_hash'],source,private,row['path'])

    def allowed(doc, content_hash, provider=None):
        value=current.get(doc)
        return bool(value and value[0]==content_hash and
                    (provider is None or value[1].allows_model(provider,value[2],value[3])))

    def usable(result):
        def evidence_allowed(e):
            if e.get('kind')=='external':
                from datetime import datetime
                try:
                    return clock()-datetime.fromisoformat(e['retrieved_at']).timestamp()<3600
                except (KeyError,TypeError,ValueError):
                    return False
            return allowed(e.get('document_id'),e.get('content_hash'),result['provider'])
        return (isinstance(result,dict) and isinstance(result.get('evidence'),list)
                and bool(result['evidence']) and isinstance(result.get('provider'),str)
                and all(isinstance(e,dict) and evidence_allowed(e) for e in result['evidence']))

    report={'vectors_removed':0,'model_results_cleared':0,'validation_files_removed':0}
    path=home/'semantic.sqlite3'
    if path.exists():
        with closing(sqlite3.connect(path,timeout=30)) as db,db:
            db.execute('PRAGMA secure_delete=ON')
            rows=db.execute('SELECT DISTINCT scope,document,content_hash FROM vectors').fetchall()
            for scope,doc,content_hash in rows:
                provider=scope.split(':')[1] if scope.startswith('provider:') else None
                if not allowed(doc,content_hash,provider):
                    report['vectors_removed']+=db.execute(
                        'DELETE FROM vectors WHERE scope=? AND document=?',(scope,doc)).rowcount
    path=home/'pa1.sqlite3'
    if path.exists():
        with closing(sqlite3.connect(path,timeout=30)) as db,db:
            db.execute('PRAGMA secure_delete=ON')
            rows=db.execute('SELECT node,request_id,response,at FROM model_calls WHERE response IS NOT NULL').fetchall()
            for node,request_id,payload,created in rows:
                try:
                    keep=created>=clock()-30*86400 and usable(json.loads(payload))
                except (TypeError,ValueError):
                    keep=False
                if not keep:
                    db.execute('UPDATE model_calls SET response=NULL WHERE node=? AND request_id=?',(node,request_id))
                    report['model_results_cleared']+=1
    folder=home/'pa1-validation'
    if folder.is_dir() and not folder.is_symlink():
        for path in folder.glob('pa1-*.json'):
            if path.is_symlink():
                continue
            keep=path.stat().st_mtime>=clock()-30*86400
            base=path.with_name(path.name.removesuffix('-provider.json')+'.json') if path.name.endswith('-provider.json') else path
            try:
                # Raw provider responses are usable only while their associated
                # validated result remains current and authorized.
                keep=keep and base.is_file() and not base.is_symlink() and usable(json.loads(base.read_text()))
            except (OSError,ValueError,TypeError):
                keep=False
            if not keep:
                path.unlink(missing_ok=True)
                report['validation_files_removed']+=1
    from .agent import clean_sessions
    report['agent_sessions_cleared']=clean_sessions(home)
    return report

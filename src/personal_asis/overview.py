"""Independent, read-only overview of private business sources and observations."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def read_json(path, limit=8192):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        return None
    return json.loads(path.read_text())


def observation(value, now, max_age):
    if not isinstance(value,str):
        return 'unknown'
    try:
        at=datetime.fromisoformat(value)
        if at.tzinfo is None or at.timestamp()>now+60:
            return 'unknown'
        return 'fresh' if now-at.timestamp()<=max_age else 'stale'
    except ValueError:
        return 'unknown'


def connect(path):
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError()
    db=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.25)
    db.row_factory=sqlite3.Row
    return db


def snapshot(home, *, now=None, router_home=None):
    home=Path(home);now=datetime.now(timezone.utc).timestamp() if now is None else now
    at=datetime.fromtimestamp(now,timezone.utc).isoformat()
    result=dict(version=1,observed_at=at,
        chat=dict(state='unknown',source='AstrBot插件心跳',observed_at=None),
        router=dict(state='unknown',source='Router本地调用账本',observed_at=None),
        mac=dict(state='not_connected',source='Mac最近同步检查',observed_at=None),
        library=dict(state='not_connected',source='共享资料副本',observed_at=None),
        memory=dict(state='not_configured',source='共享记忆服务',observed_at=None),
        work=dict(state='not_connected',source='Work只读适配器',observed_at=None),
        pending=dict(feedback=None,journal=None,calendar_state='session_only',source='业务队列／Mac最近检查',observed_at=at),
        recent=[],notice='最近观测和同步快照不代表另一端实时在线；未记录不等于未发生。')
    try:
        status=read_json(home/'chat-status.json')
        if status and type(status.get('ready')) is bool and isinstance(status.get('version'),str) and len(status['version'])<=24:
            freshness=observation(status.get('observed_at'),now,90)
            result['chat'].update(state='running' if status['ready'] and freshness=='fresh' else 'stopped' if not status['ready'] and freshness=='fresh' else freshness,
                version=status['version'],observed_at=status.get('observed_at'))
    except (OSError,ValueError,TypeError):
        pass
    try:
        from .life_status import validate
        mac=read_json(home/'mac-status.json')
        if mac:
            validate(mac)
            result['mac'].update(state=observation(mac['checked_at'],now,86400),observed_at=mac['checked_at'],sources=mac['sources'])
            result['pending'].update(journal=mac['pending'],journal_observed_at=mac['checked_at'])
    except (OSError,ValueError,TypeError,KeyError):
        pass
    try:
        with closing(connect(home/'life.sqlite3')) as db:
            for row in db.execute("SELECT id,payload FROM records WHERE coalesce(json_extract(payload,'$.deleted'),0)=0 AND coalesce(json_extract(payload,'$.entry_excluded'),0)=0 AND json_extract(payload,'$.capture_source')='life_command' ORDER BY json_extract(payload,'$.occurred_at') DESC,id LIMIT 5"):
                r=json.loads(row['payload'])
                result['recent'].append(dict(record_id=row['id'],revision=r['revision'],day=r['day'],text=r['text'][:180],kind=r['kind'],source='主动随记原话',observed_at=r['updated_at']))
            counts=dict(db.execute("SELECT state,count(*) FROM feedback_jobs GROUP BY state"))
            result['pending'].update(feedback=sum(counts.get(k,0) for k in ('pending','running')),feedback_unknown=counts.get('unknown',0))
    except (OSError,sqlite3.Error,ValueError,TypeError,KeyError):
        pass
    try:
        with closing(connect(home/'shared.sqlite3')) as db:
            meta={r['key']:json.loads(r['value']) for r in db.execute("SELECT key,value FROM meta WHERE key IN ('mac_last_received','mac_snapshot')")}
            stamp=meta.get('mac_last_received')
            result['library'].update(state=observation(stamp,now,86400),observed_at=stamp,replica_complete=bool(meta.get('mac_snapshot',{}).get('complete')))
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    try:
        router_home=Path(router_home) if router_home else home.parent/'personal-asis-router'
        with closing(connect(router_home/'router.sqlite3')) as db:
            pacific=ZoneInfo('America/Los_Angeles')
            start=datetime.fromtimestamp(now,pacific).replace(hour=0,minute=0,second=0,microsecond=0)
            rows=[dict(r) for r in db.execute('SELECT model,count(*) AS requests FROM attempts WHERE started>=? GROUP BY model',(start.timestamp(),))]
            latest=db.execute('SELECT model,status,started FROM attempts ORDER BY id DESC LIMIT 1').fetchone()
            result['router'].update(state='observed',models=rows,total_requests=sum(r['requests'] for r in rows),
                reset_at=(start+timedelta(days=1)).isoformat(),label='本地调用观测，不是官方剩余额度',
                observed_at=datetime.fromtimestamp(latest['started'],timezone.utc).isoformat() if latest else None,
                last_model=latest['model'] if latest else None,last_status=latest['status'] if latest else None)
    except (OSError,sqlite3.Error,ValueError,TypeError):
        pass
    return result

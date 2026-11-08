"""Narrow activation with rollback prepared before service/config changes."""
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time


def run(*args):return subprocess.run(args,check=True,capture_output=True,text=True)


def main(stage):
    os.umask(0o077)
    stage=Path(stage).resolve()
    if not stage.is_relative_to('/home/mac/personal-asis-router-incoming'):
        raise ValueError('router_stage_required')
    manifest=json.loads((stage/'manifest.json').read_text())
    for name,digest in manifest.items():
        p=stage/name
        if p.is_symlink() or not p.resolve().is_relative_to(stage) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            raise ValueError('router_release_integrity')
    test=run(sys.executable,str(stage/'validate-router-sdk.py'),str(stage))
    print(test.stdout.strip().splitlines()[-1],flush=True)
    data=Path('/home/mac/astrbot/data');plugins=data/'plugins'
    cfg=json.loads((data/'cmd_config.json').read_text(encoding='utf-8-sig'))
    owner=json.loads((data/'config/astrbot_plugin_life_agent_config.json').read_text(encoding='utf-8-sig'))
    if not owner.get('owner_id') or not owner.get('owner_platform'):raise ValueError('existing_binding_required')
    life=sqlite3.connect('file:/home/mac/.local/share/personal-asis-life/life.sqlite3?mode=ro',uri=True)
    owner_hash=hashlib.sha256((owner['owner_platform']+'\0'+owner['owner_id']).encode()).hexdigest()
    row=life.execute('SELECT payload FROM attention_policy WHERE owner=?',(owner_hash,)).fetchone()
    life.close()
    origin=json.loads(row[0]).get('origin') if row else None
    if not origin or not origin.startswith(owner['owner_platform']+':FriendMessage:'):
        raise ValueError('existing_private_origin_required')
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup=Path('/home/mac/personal-asis-router-rollbacks')/stamp;backup.mkdir(parents=True,mode=0o700)
    profile_id='personal-asis-smart-router';profile_file='abconf_personal-asis-smart-router.json'
    profile=data/'config'/profile_file
    state=dict(plugins={},profile_file=profile_file,profile_existed=profile.exists(),preferences=[])
    metadata=Path('/home/mac/.local/share/personal-asis-router/deployment.json')
    state['deployment_metadata_existed']=metadata.exists()
    if metadata.exists():
        prior=json.loads(metadata.read_text())
        # A disconnected old caller may have reported a newer release before
        # rolling back. Bind the rollback receipt to the actual runtime files.
        for candidate in sorted(Path('/home/mac/personal-asis-router-releases').glob('*'),reverse=True):
            candidate_manifest=candidate/'manifest.json'
            if not candidate_manifest.exists():continue
            matching=True
            for name,digest in json.loads(candidate_manifest.read_text()).items():
                if name.startswith('astrbot_plugin_smart_router/'):current=plugins/name
                elif name in ('briefing_agent.py','feedback_agent.py'):current=plugins/'astrbot_plugin_life_agent'/name
                else:continue
                if not current.exists() or hashlib.sha256(current.read_bytes()).hexdigest()!=digest:
                    matching=False;break
            if matching:
                prior.update(release=str(candidate),backup=str(Path('/home/mac/personal-asis-router-rollbacks')/candidate.name))
                break
        (backup/'deployment-before.json').write_text(json.dumps(prior))
    for name in ('astrbot_plugin_smart_router','astrbot_plugin_life_agent'):
        state['plugins'][name]=(plugins/name).exists()
        if state['plugins'][name]:shutil.copytree(plugins/name,backup/name)
    shutil.copyfile(data/'cmd_config.json',backup/'cmd_config.json')
    if profile.exists():shutil.copyfile(profile,backup/'owner-profile.json')
    # Preferences values use a {val: ...} envelope in this AstrBot version.
    db=sqlite3.connect(data/'data_v4.db')
    def get(scope,scope_id,key):
        row=db.execute('SELECT value FROM preferences WHERE scope=? AND scope_id=? AND key=?',(scope,scope_id,key)).fetchone()
        state['preferences'].append(dict(scope=scope,scope_id=scope_id,key=key,old=row[0] if row else None))
        value=json.loads(row[0]) if row else {}
        return value.get('val',{}) if isinstance(value,dict) else value
    mapping=get('global','global','abconf_mapping') or {}
    routes=get('global','global','umop_config_routing') or {}
    get('umo',origin,'provider_perf_chat_completion')
    (backup/'rollback.json').write_text(json.dumps(state))
    shutil.copyfile(stage/'rollback-router-vps.py',backup/'rollback.py')
    (backup/'rollback.sh').write_text('#!/bin/sh\nexec /home/mac/.local/share/uv/tools/astrbot/bin/python "$(dirname "$0")/rollback.py"\n')
    (backup/'rollback.sh').chmod(0o700)
    release=Path('/home/mac/personal-asis-router-releases')/stamp;release.parent.mkdir(mode=0o700,exist_ok=True)
    shutil.copytree(stage,release)
    try:
        run('sudo','systemctl','stop','astrbot.service')
        # Copy the owning configuration, leaving defaults and other sessions untouched.
        from astrbot.core.umop_config_router import UmopConfigRouter
        router=UmopConfigRouter.__new__(UmopConfigRouter);router.umop_to_conf_id=routes
        previous=router.get_conf_id_for_umop(origin)
        previous_meta=mapping.get(previous,{})
        current=data/'config'/previous_meta.get('path','')
        owner_cfg=json.loads(current.read_text(encoding='utf-8-sig')) if current.is_file() else json.loads(json.dumps(cfg))
        ids={p.get('id') for p in cfg['provider']}
        for model in ('auto','complex','summary'):
            entry=dict(id='asis_router/'+model,type='asis_smart_router',provider_type='chat_completion',
                enable=True,model=model,key=[''],max_context_tokens=0,
                modalities=['text','image','audio','tool_use'])
            if entry['id'] not in ids:cfg['provider'].append(entry)
        owner_cfg['provider_settings'].update(default_provider_id='asis_router/auto',fallback_chat_models=[],
            request_max_retries=1,max_context_length=-1,llm_compress_provider_id='asis_router/summary',
            streaming_response=False)
        mapping[profile_id]=dict(path=profile_file,name='Personal Asis Smart Router')
        routes[origin]=profile_id
        db.execute('BEGIN IMMEDIATE')
        for item,value in zip(state['preferences'],(mapping,routes,'asis_router/auto')):
            db.execute('DELETE FROM preferences WHERE scope=? AND scope_id=? AND key=?',
                       (item['scope'],item['scope_id'],item['key']))
            db.execute('INSERT INTO preferences(created_at,updated_at,scope,scope_id,key,value) '
                'VALUES(CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?,?,?,?)',
                (item['scope'],item['scope_id'],item['key'],json.dumps({'val':value})))
        profile.write_text(json.dumps(owner_cfg,ensure_ascii=False));profile.chmod(0o600)
        (data/'cmd_config.json').write_text(json.dumps(cfg,ensure_ascii=False));(data/'cmd_config.json').chmod(0o600)
        target=plugins/'astrbot_plugin_smart_router'
        if target.exists():shutil.rmtree(target)
        shutil.copytree(release/'astrbot_plugin_smart_router',target)
        for name in ('briefing_agent.py','feedback_agent.py','model_display.py'):
            shutil.copyfile(release/name,plugins/'astrbot_plugin_life_agent'/name)
        db.commit();db.close()
        run('sudo','systemctl','start','astrbot.service')
        # Read-only service evidence; never call models or send platform messages.
        pid=run('systemctl','show','astrbot.service','-p','MainPID','--value').stdout.strip()
        deadline=time.monotonic()+240
        while time.monotonic()<deadline:
            logs=run('journalctl','-u','astrbot.service','_PID='+pid,'--no-pager','-o','cat').stdout
            if (all('Loading model asis_smart_router(asis_router/'+p+')' in logs for p in ('auto','complex','summary'))
                    and 'AstrBot started.' in logs):
                break
            time.sleep(1)
        if not all('Loading model asis_smart_router(asis_router/'+p+')' in logs for p in ('auto','complex','summary')):
            raise ValueError('router_provider_registration_not_observed')
        if 'AstrBot started.' not in logs:
            raise ValueError('router_service_readiness_not_observed')
        if any(s in logs for s in ('Failed to load plugin astrbot_plugin_smart_router','Provider adapter not found: asis_smart_router')):
            raise ValueError('router_startup_failed')
        run('systemctl','is-active','astrbot.service')
        pending=metadata.with_suffix('.next')
        pending.write_text(json.dumps(dict(release=str(release),backup=str(backup),profile=profile_id)))
        pending.replace(metadata)
    except BaseException:
        if db:
            try:db.rollback();db.close()
            except Exception:pass
        run(sys.executable,str(backup/'rollback.py'))
        raise
    # A closed chat/SSH output channel must not undo a completed healthy release.
    try:
        print(json.dumps(dict(release=str(release),backup=str(backup),service='active',
            registered_profiles=3,owner_route='isolated',real_generations=0)),flush=True)
    except BrokenPipeError:
        pass


if __name__=='__main__':
    private=Path('/home/mac/.local/share/personal-asis-router')
    private.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (private/'deploy.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        signal.signal(signal.SIGHUP,signal.SIG_IGN)
        main(sys.argv[1])

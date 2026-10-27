#!/usr/bin/env python3
"""Remote activation. Back up current release/plugin/units; restore on failure."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys


def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True)


def main(stage):
    os.umask(0o077)
    stage=Path(stage).resolve()
    if not stage.is_relative_to(Path('/home/mac/personal-asis-v2-incoming')):
        raise ValueError('unexpected_stage')
    manifest=json.loads((stage/'manifest.json').read_text())
    for name,expected in manifest.items():
        p=stage/name
        if not p.resolve().is_relative_to(stage) or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
            raise ValueError('release_integrity_failed')
    # Validate native tool schemas and synthetic behavior before stopping services.
    try:
        preflight = run('/home/mac/.local/share/uv/tools/astrbot/bin/python', str(stage/'validate-life-sdk.py'), str(stage))
        print(preflight.stdout.strip().splitlines()[-1],flush=True)
    except subprocess.CalledProcessError as error:
        # This fixture only uses temporary synthetic state; expose its failure
        # before stopping any service, without ever printing private config.
        print(error.stderr[-8000:],file=sys.stderr,flush=True)
        raise
    stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup=Path('/home/mac/personal-asis-v2-rollbacks')/stamp;backup.mkdir(parents=True,mode=0o700)
    plugins=Path('/home/mac/astrbot/data/plugins');config_dir=plugins.parent/'config'
    units=Path('/etc/systemd/system')
    managed=('personal-asis-pwa.service','personal-asis-coordinator.service','personal-asis-dashboard.service')
    previous_units={name:(units/name).exists() for name in managed}
    for name,present in previous_units.items():
        if present:shutil.copyfile(units/name,backup/name)
    names=('astrbot_plugin_personal_asis','astrbot_plugin_life_agent')
    previous_plugins={name:(plugins/name).exists() for name in names}
    for name,present in previous_plugins.items():
        if present:shutil.copytree(plugins/name,backup/name)
        config=config_dir/(name+'_config.json')
        if config.exists():shutil.copyfile(config,backup/config.name)
    link=Path('/home/mac/personal-asis-v2')
    if link.exists() and not link.is_symlink():raise ValueError('release_link_required')
    previous_link=os.readlink(link) if link.is_symlink() else None
    home=Path('/home/mac/.local/share/personal-asis-life');home.mkdir(mode=0o700,exist_ok=True)
    current=config_dir/'astrbot_plugin_life_agent_config.json'
    if current.exists():
        config=json.loads(current.read_text(encoding='utf-8-sig'))
    else:
        old=Path('/home/mac/.local/share/personal-asis-coordinator')
        db=sqlite3.connect('file:'+str(old/'feishu.sqlite3')+'?mode=ro',uri=True)
        row=db.execute('SELECT platform_id,open_id FROM binding WHERE singleton=1').fetchone();db.close()
        if not row or not all(row):raise ValueError('existing_owner_binding_required')
        config=dict(owner_platform=row[0],owner_id=row[1],capture_enabled=True,reminders_enabled=True)
    if not (home/'web-auth.sqlite3').exists():
        src=sqlite3.connect('file:/home/mac/.local/share/personal-asis-coordinator/web-auth.sqlite3?mode=ro',uri=True)
        dest=sqlite3.connect(home/'web-auth.sqlite3');src.backup(dest);src.close()
        dest.execute('DELETE FROM web_sessions');dest.execute('DELETE FROM bootstrap');dest.commit();dest.close()
        (home/'web-auth.sqlite3').chmod(0o600)
    release=Path('/home/mac/personal-asis-v2-releases')/stamp;release.parent.mkdir(mode=0o700,exist_ok=True)
    shutil.copytree(stage,release)
    state=dict(previous_units=previous_units,previous_plugins=previous_plugins,previous_link=previous_link)
    (backup/'rollback.json').write_text(json.dumps(state))
    # Rollback script is in place before any active service is changed.
    rollback=backup/'rollback.py';shutil.copyfile(Path(__file__).with_name('rollback-life-vps.py'),rollback)
    (backup/'rollback.sh').write_text('#!/bin/sh\nexec python3 "$(dirname "$0")/rollback.py"\n');(backup/'rollback.sh').chmod(0o700)
    try:
        run('sudo','systemctl','stop','astrbot.service')
        life_db = home/'life.sqlite3'
        if life_db.exists():
            src = sqlite3.connect(life_db.as_uri()+'?mode=ro', uri=True)
            dest = sqlite3.connect(backup/'life-before.sqlite3')
            try:
                src.backup(dest)
            finally:
                dest.close(); src.close()
            (backup/'life-before.sqlite3').chmod(0o600)
        for name in managed:
            if previous_units[name]:run('sudo','systemctl','disable','--now',name)
        for name in names:
            if (plugins/name).exists():shutil.rmtree(plugins/name)
        old_config=config_dir/'astrbot_plugin_personal_asis_config.json'
        old_config.unlink(missing_ok=True)
        shutil.copytree(release/'astrbot_plugin_life_agent',plugins/'astrbot_plugin_life_agent')
        current.write_text(json.dumps(config));current.chmod(0o600)
        temporary=link.with_name('personal-asis-v2-next');temporary.unlink(missing_ok=True);temporary.symlink_to(release,target_is_directory=True);temporary.replace(link)
        # Services are stopped and SQLite has been backed up. Retag legacy
        # conversation memory and withdraw invalid derived observations once.
        result=run('/usr/bin/python3','-c',
            'import sys,json;sys.path.insert(0,"/home/mac/personal-asis-v2/src");'
            'from personal_asis.life_store import LifeStore;'
            's=LifeStore("/home/mac/.local/share/personal-asis-life/life.sqlite3");'
            'print(json.dumps(s.reconcile_intake()));s.close()')
        print(result.stdout.strip())
        for name in managed[:2]:run('sudo','rm','-f',str(units/name))
        run('sudo','install','-m','644',str(release/'personal-asis-dashboard.service'),str(units/managed[2]))
        run('sudo','systemctl','daemon-reload');run('sudo','nginx','-t')
        run('sudo','systemctl','enable','--now',managed[2]);run('sudo','systemctl','start','astrbot.service')
        run('sudo','systemctl','is-active',managed[2],'astrbot.service')
    except BaseException:
        subprocess.run(['python3',str(rollback)],check=True)
        raise
    print(json.dumps(dict(release=str(release),backup=str(backup),files=len(manifest))))


if __name__=='__main__':
    main(sys.argv[1])

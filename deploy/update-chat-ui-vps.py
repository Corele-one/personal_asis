#!/usr/bin/env python3
"""Code-only C6 follow-up on an already validated Life bundle; no config/data restore."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

ALLOWED = {'astrbot_plugin_life_agent/main.py','astrbot_plugin_life_agent/chat_interaction.py',
           'astrbot_plugin_life_agent/chat_ui.py','validate-life-sdk.py','validate-chat-ui-sdk.py'}
ROOT=Path('/home/mac')
PYTHON=ROOT/'.local/share/uv/tools/astrbot/bin/python'
LINK=ROOT/'personal-asis-v2'
PLUGIN=ROOT/'astrbot/data/plugins/astrbot_plugin_life_agent'

def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=300)

def update(archive,expected,accepted):
    os.umask(0o077)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
        raise ValueError('archive_hash_mismatch')
    old=LINK.resolve(strict=True)
    if old.name != accepted:
        raise ValueError('explicit_previously_accepted_release_required')
    manifest=json.loads((old/'manifest.json').read_text())
    core='astrbot_plugin_life_agent/chat_ui.py'

    for name,digest in manifest.items():
        if name.startswith('astrbot_plugin_life_agent/'):
            live=PLUGIN/Path(name).relative_to('astrbot_plugin_life_agent')
            if hashlib.sha256(live.read_bytes()).hexdigest()!=digest:
                raise ValueError('live_code_drift_review_required')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    release=ROOT/'personal-asis-v2-releases'/stamp
    shutil.copytree(old,release,ignore=shutil.ignore_patterns('__pycache__'))
    with tarfile.open(archive) as bundle:
        members=bundle.getmembers()
        if {m.name for m in members} != ALLOWED or any(not m.isfile() for m in members):
            raise ValueError('unexpected_update_files')
        bundle.extractall(release,filter='data')
    if hashlib.sha256((release/core).read_bytes()).hexdigest()!=manifest[core]:
        raise ValueError('changed_conversation_logic_requires_full_native_acceptance')
    # Router and background-isolation code must be identical to the accepted bundle.
    for name,digest in manifest.items():
        if name not in ALLOWED and hashlib.sha256((release/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('unrelated_bundle_change')
    updated={str(p.relative_to(release)):hashlib.sha256(p.read_bytes()).hexdigest()
             for p in release.rglob('*') if p.is_file() and p.name!='manifest.json' and '__pycache__' not in p.parts}
    (release/'manifest.json').write_text(json.dumps(updated))
    for check in ['validate-life-sdk.py']:
        result=run(str(PYTHON),str(release/check),str(release))
        print(result.stdout.strip().splitlines()[-1],flush=True)
    backup=ROOT/'personal-asis-v2-rollbacks'/stamp
    backup.mkdir(mode=0o700)
    shutil.copytree(PLUGIN,backup/'astrbot_plugin_life_agent',ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copytree(ROOT/'astrbot/data/config',backup/'config-evidence')
    (backup/'previous-link').write_text(str(old))
    rollback = """#!/usr/bin/env python3
from pathlib import Path
import shutil,subprocess
root=Path('/home/mac')
backup=Path(__file__).resolve().parent
subprocess.run(['sudo','systemctl','stop','astrbot'],check=True)
target=root/'astrbot/data/plugins/astrbot_plugin_life_agent'
shutil.rmtree(target)
shutil.copytree(backup/'astrbot_plugin_life_agent',target)
link=root/'personal-asis-v2';link.unlink();link.symlink_to((backup/'previous-link').read_text())
subprocess.run(['sudo','systemctl','start','astrbot'],check=True)
"""
    (backup/'rollback.py').write_text(rollback)
    (backup/'rollback.sh').write_text('#!/bin/sh\nexec python3 "$(dirname "$0")/rollback.py"\n')
    (backup/'rollback.sh').chmod(0o700)
    try:
        run('sudo','systemctl','stop','astrbot')
        shutil.rmtree(PLUGIN)
        shutil.copytree(release/'astrbot_plugin_life_agent',PLUGIN,ignore=shutil.ignore_patterns('__pycache__'))
        temporary=LINK.with_name('personal-asis-v2-c6-next')
        temporary.unlink(missing_ok=True);temporary.symlink_to(release);temporary.replace(LINK)
        run('sudo','systemctl','start','astrbot')
        run('sudo','systemctl','is-active','astrbot')
    except BaseException:
        run('python3',str(backup/'rollback.py'))
        raise
    print(json.dumps(dict(release=str(release),backup=str(backup),files=len(updated),
        only_chat_restarted=True,config_or_database_restored=False,unchanged_sdk_checks_reused=['router','background_isolation','native_C6_conversations'],accepted_c6_release=accepted)),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive',type=Path);p.add_argument('--sha256',required=True);p.add_argument('--accepted-c6-release',required=True)
    a=p.parse_args();update(a.archive,a.sha256,a.accepted_c6_release)

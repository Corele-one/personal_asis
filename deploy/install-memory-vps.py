#!/usr/bin/env python3
"""Install isolated, synthetic-only M1 service; never imports personal history."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import pwd
import secrets
import shutil
import subprocess
import tarfile
import time
import urllib.request

ROOT=Path('/opt/personal-asis-memory')
HOME=Path('/var/lib/personal-asis-memory')
UNIT=Path('/etc/systemd/system/personal-asis-memory.service')


def run(*args):
    return subprocess.run(args,check=True,capture_output=True,text=True)


def install(archive,digest):
    if run('id','-u').stdout.strip()!='0' or hashlib.sha256(archive.read_bytes()).hexdigest()!=digest:
        raise ValueError('root_and_verified_archive_required')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    ROOT.mkdir(mode=0o755,exist_ok=True)
    backup=Path('/var/backups/personal-asis-memory')/stamp
    backup.mkdir(parents=True,mode=0o700);backup.chmod(0o700)
    current=ROOT/'current'
    previous=str(current.resolve()) if current.exists() else None
    active=subprocess.run(['systemctl','is-active','--quiet','personal-asis-memory']).returncode==0
    (backup/'state.json').write_text(json.dumps(dict(previous=previous,active=active)))
    if UNIT.exists():
        shutil.copyfile(UNIT,backup/UNIT.name)
    try:
        account=pwd.getpwnam('asis-memory')
    except KeyError:
        run('useradd','--system','--user-group','--home-dir',str(HOME),'--shell','/usr/sbin/nologin','asis-memory')
        account=pwd.getpwnam('asis-memory')
    if account.pw_dir!=str(HOME) or account.pw_shell!='/usr/sbin/nologin':
        raise ValueError('unexpected_service_identity')
    HOME.mkdir(mode=0o700,exist_ok=True)
    HOME.chmod(0o700);shutil.chown(HOME,user='asis-memory',group='asis-memory')
    venv=ROOT/'venv'
    if not venv.exists():
        shutil.copytree('/home/mac/.local/opt/personal-asis-memory-pilot/venv',venv,symlinks=True)
        run('chown','-R','root:root',str(venv));run('chmod','-R','go-w',str(venv))
        venv.chmod(0o755)
    runtime=ROOT/'runtime'
    if not runtime.exists():
        original=Path(run('/home/mac/.local/opt/personal-asis-memory-pilot/venv/bin/python','-c',
            'import sys;print(sys.base_prefix)').stdout.strip()).resolve()
        if not str(original).startswith('/home/mac/.local/share/uv/python/cpython-3.12.14-'):
            raise ValueError('unexpected_existing_python_runtime')
        shutil.copytree(original,runtime,symlinks=True)
        run('chown','-R','root:root',str(runtime));run('chmod','-R','go-w',str(runtime))
        runtime.chmod(0o755)
    # The pilot venv points into its owner's private uv installation. Relocate
    # its existing interpreter as well; never expose that home to the service.
    for name in ['python','python3','python3.12']:
        link=venv/'bin'/name;link.unlink(missing_ok=True);link.symlink_to(runtime/'bin/python3.12')
    (venv/'pyvenv.cfg').write_text('home = '+str(runtime/'bin')+'\ninclude-system-site-packages = false\nversion = 3.12.14\nexecutable = '+str(runtime/'bin/python3.12')+'\n')
    versions=run(str(venv/'bin/python'),'-c',
        "import importlib.metadata as m,json; print(json.dumps({k:m.version(k) for k in ['mem0ai','google-genai']}))").stdout
    if json.loads(versions)!={'mem0ai':'2.2.1','google-genai':'2.18.1'}:
        raise ValueError('unexpected_pinned_dependencies')
    private=HOME/'config.json'
    if not private.exists():
        cfg=json.loads(Path('/home/mac/astrbot/data/cmd_config.json').read_text(encoding='utf-8-sig'))
        google=next(s for s in cfg['provider_sources'] if s.get('type')=='googlegenai_chat_completion' and s.get('enable',True))
        mimo=next(s for s in cfg['provider_sources'] if s.get('id')=='xiaomi')
        if mimo.get('api_base')!='https://api.xiaomimimo.com/v1' or len(mimo['key'])!=1:
            raise ValueError('unexpected_approved_extraction_source')
        key=google['key'][0] if isinstance(google['key'],list) else google['key']
        tokens={name:secrets.token_urlsafe(32) for name in ['acceptance-chat','acceptance-work','acceptance-admin']}
        data=dict(mode='synthetic_only',embedding=dict(key=key,base_url=google.get('api_base')),
            extraction=dict(key=mimo['key'][0],base_url=mimo['api_base'],model='mimo-v2.6-flash'),tokens=tokens)
        fd=__import__('os').open(private,__import__('os').O_CREAT|__import__('os').O_EXCL|__import__('os').O_WRONLY,0o600)
        with __import__('os').fdopen(fd,'w') as output:json.dump(data,output)
        shutil.chown(private,user='asis-memory',group='asis-memory')
        client=Path('/home/mac/.local/share/personal-asis-memory-acceptance')
        client.mkdir(mode=0o700,exist_ok=True);client.chmod(0o700)
        shutil.chown(client,user='mac',group='mac')
        target=client/'clients.json';target.write_text(json.dumps(tokens));target.chmod(0o600)
        shutil.chown(target,user='mac',group='mac')
    elif json.loads(private.read_text()).get('mode')!='synthetic_only':
        raise ValueError('refuse_to_change_real_memory_service')
    release=ROOT/'releases'/stamp;release.mkdir(parents=True,mode=0o755)
    with tarfile.open(archive) as bundle:
        if any(m.name.startswith('/') or '..' in Path(m.name).parts for m in bundle.getmembers()):
            raise ValueError('unsafe_archive')
        bundle.extractall(release,filter='data')
    run('chown','-R','root:root',str(release));run('chmod','-R','go-w',str(release))
    try:
        run('systemctl','stop','personal-asis-memory') if active else None
        shutil.copyfile(release/'deploy/personal-asis-memory.service',UNIT);UNIT.chmod(0o644)
        run('systemd-analyze','verify',str(UNIT))
        link=ROOT/'.next';link.unlink(missing_ok=True);link.symlink_to(release);link.replace(current)
        run('systemctl','daemon-reload');run('systemctl','start','personal-asis-memory')
        token=json.loads(private.read_text())['tokens']['acceptance-admin']
        for attempt in range(30):
            try:
                req=urllib.request.Request('http://127.0.0.1:23101/v1/memory',method='POST',
                    data=b'{"action":"status","arguments":{}}',headers={'Authorization':'Bearer '+token})
                with urllib.request.urlopen(req,timeout=3) as response:status=json.load(response)
                if status['storage_ready'] and status['consistency_ready']:
                    break
            except Exception:
                pass
            if attempt==29:
                raise ValueError('service_not_ready')
            time.sleep(1)
        run('systemctl','enable','personal-asis-memory')
    except Exception:
        rollback(backup)
        raise
    print(json.dumps(dict(release=stamp,backup=str(backup),synthetic_only=True,ready=True,
        automatic_capture=False,personal_content_imported=False)))


def rollback(backup):
    state=json.loads((backup/'state.json').read_text())
    run('systemctl','stop','personal-asis-memory')
    current=ROOT/'current';current.unlink(missing_ok=True)
    if state['previous']:current.symlink_to(state['previous'])
    saved=backup/UNIT.name
    if saved.exists():shutil.copyfile(saved,UNIT)
    else:
        subprocess.run(['systemctl','disable','personal-asis-memory'],capture_output=True)
        UNIT.unlink(missing_ok=True)
    run('systemctl','daemon-reload')
    if state['active']:run('systemctl','start','personal-asis-memory')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive',nargs='?',type=Path)
    parser.add_argument('--sha256');parser.add_argument('--rollback',type=Path);args=parser.parse_args()
    try:
        rollback(args.rollback) if args.rollback else install(args.archive,args.sha256)
    except Exception as error:
        raise SystemExit('memory_install_failed:'+type(error).__name__) from None

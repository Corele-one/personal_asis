#!/usr/bin/env python3
"""Offline, consistent engine checkpoints; never roll back live version barriers.

Backups include a copy of barriers for disaster recovery, but an ordinary restore
keeps the current barriers. A fresh host requires an independently verified latest
barrier copy; this tool deliberately refuses to bootstrap from an arbitrary old one.
"""
import argparse
from datetime import datetime,timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess

HOME=Path('/var/lib/personal-asis-memory')
BACKUPS=Path('/var/backups/personal-asis-memory-data')


def sequence(path):
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        return db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]


def hashes(directory):
    result={}
    for p in directory.rglob('*'):
        if p.is_symlink():
            raise ValueError('checkpoint_symlink_denied')
        if p.is_file() and p.relative_to(directory)!=Path('manifest.json'):
            result[str(p.relative_to(directory))]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def backup(target):
    target.mkdir(parents=True,mode=0o700)
    target.chmod(0o700)
    shutil.copytree(HOME/'engine',target/'engine')
    shutil.copyfile(HOME/'barriers.sqlite3',target/'barriers.sqlite3')
    # Credentials and billed-call reservations are intentionally not rolled back.
    (target/'manifest.json').write_text(json.dumps(dict(version=1,sequence=sequence(HOME/'barriers.sqlite3'),
        files=hashes(target),credentials_included=False)))
    return dict(checkpoint=str(target),sequence=sequence(HOME/'barriers.sqlite3'))


def restore(target):
    manifest=json.loads((target/'manifest.json').read_text())
    if manifest['files']!=hashes(target):
        raise ValueError('checkpoint_digest_mismatch')
    live=HOME/'barriers.sqlite3'
    if not live.exists() or sequence(live)<manifest['sequence']:
        raise ValueError('latest_barriers_required_before_restore')
    # Preserve newer engine data before the explicit restore; never delete it.
    saved=HOME/('engine-before-restore-'+datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f'))
    (HOME/'engine').rename(saved)
    shutil.copytree(target/'engine',HOME/'engine')
    subprocess.run(['chown','-R','asis-memory:asis-memory',str(HOME/'engine')],check=True)
    return dict(restored_engine=True,barriers_rolled_back=False,calls_rolled_back=False,
        checkpoint_sequence=manifest['sequence'],current_sequence=sequence(live))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('--checkpoint',type=Path);args=parser.parse_args()
    if os.getuid()!=0:
        raise SystemExit('root_required')
    os.umask(0o077)
    active=subprocess.run(['systemctl','is-active','--quiet','personal-asis-memory']).returncode==0
    subprocess.run(['systemctl','stop','personal-asis-memory'],check=True)
    try:
        with (HOME/'.holder.lock').open('a+b') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if args.action=='backup':
                target=args.checkpoint or BACKUPS/datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
                result=backup(target)
            else:
                if not args.checkpoint:
                    raise ValueError('checkpoint_required')
                result=restore(args.checkpoint)
        print(json.dumps(result))
    except Exception as error:
        raise SystemExit('memory_checkpoint_failed:'+type(error).__name__) from None
    finally:
        if active:
            subprocess.run(['systemctl','start','personal-asis-memory'],check=True)

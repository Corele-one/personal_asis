#!/usr/bin/env python3
"""Install a versioned read interface, preserving all source and Work data."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import time

ROOT = Path('/opt/personal-asis-knowledge')
UNIT = Path('/etc/systemd/system/personal-asis-knowledge.service')
CONF = Path('/etc/personal-asis-knowledge.conf')


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def install(archive, digest):
    if run('id', '-u').stdout.strip() != '0':
        raise SystemExit('root_required')
    if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
        raise SystemExit('archive_digest_mismatch')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    account = pwd.getpwnam('alma-work')
    current = ROOT/'current'
    if current.exists() and not current.is_symlink():
        raise SystemExit('unexpected_install_path')
    backup = Path('/var/backups/personal-asis-knowledge')/stamp
    backup.mkdir(parents=True, mode=0o700)
    backup.chmod(0o700)
    previous = str(current.resolve()) if current.exists() else None
    active = subprocess.run(['systemctl', 'is-active', '--quiet', 'personal-asis-knowledge']).returncode == 0
    for path in (UNIT, CONF):
        if path.exists():
            shutil.copyfile(path, backup/path.name)
    (backup/'state.json').write_text(json.dumps(dict(previous=previous, active=active)))
    releases = ROOT/'releases'
    releases.mkdir(parents=True, exist_ok=True)
    release = releases/stamp
    with tempfile.TemporaryDirectory(prefix='.stage-', dir=releases) as tmp:
        with tarfile.open(archive) as bundle:
            # Only the deliberately packaged source and pinned SDK are accepted.
            if any(m.name.startswith('/') or '..' in Path(m.name).parts for m in bundle.getmembers()):
                raise SystemExit('unsafe_archive')
            bundle.extractall(tmp, filter='data')
        shutil.move(tmp, release)
    run('chown', '-R', 'root:root', str(release))
    run('chmod', '-R', 'go-w', str(release))
    release.chmod(0o755)
    cache = Path('/home/mac/.local/share/personal-asis-life/wucai-fulltext')
    if not cache.exists():
        cache.mkdir(mode=0o700)
        shutil.chown(cache, user='mac', group='mac')
    try:
        shutil.copyfile(release/'deploy/personal-asis-knowledge.service', UNIT)
        UNIT.chmod(0o644)
        CONF.write_text('WORK_UID='+str(account.pw_uid)+'\n')
        CONF.chmod(0o600)
        run('systemd-analyze', 'verify', str(UNIT))
        temp_link = ROOT/'.next'
        temp_link.unlink(missing_ok=True)
        temp_link.symlink_to(release)
        temp_link.replace(current)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'restart', 'personal-asis-knowledge')
        probe = ("import socket,json; s=socket.socket(socket.AF_UNIX); s.settimeout(2); "
            "s.connect('/run/personal-asis-knowledge/reader.sock'); "
            "s.sendall(b'{\"method\":\"tools/list\"}\\n'); "
            "v=json.loads(s.makefile('rb').readline()); assert len(v['tools'])==2")
        for attempt in range(10):
            try:
                run('runuser', '-u', 'alma-work', '--', '/usr/bin/python3', '-c', probe)
                break
            except subprocess.CalledProcessError:
                if attempt == 9:
                    raise
                time.sleep(.5)
        run('systemctl', 'enable', 'personal-asis-knowledge')
    except Exception:
        rollback(backup)
        raise
    print(json.dumps(dict(release=stamp, backup=str(backup), installed=True,
        chat_restarted=False, work_restarted=False)))


def rollback(backup):
    state = json.loads((backup/'state.json').read_text())
    run('systemctl', 'stop', 'personal-asis-knowledge')
    current = ROOT/'current'
    current.unlink(missing_ok=True)
    if state['previous']:
        current.symlink_to(state['previous'])
    for path in (UNIT, CONF):
        saved = backup/path.name
        if saved.exists():
            shutil.copyfile(saved, path)
            path.chmod(0o600 if path == CONF else 0o644)
        else:
            path.unlink(missing_ok=True)
    if not state['previous']:
        subprocess.run(['systemctl', 'disable', 'personal-asis-knowledge'], capture_output=True)
    run('systemctl', 'daemon-reload')
    if state['active']:
        run('systemctl', 'start', 'personal-asis-knowledge')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', nargs='?', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--rollback', type=Path)
    args = parser.parse_args()
    try:
        if args.rollback:
            rollback(args.rollback)
        elif args.archive and args.sha256:
            install(args.archive, args.sha256)
        else:
            raise ValueError('archive_and_digest_required')
    except Exception as error:
        raise SystemExit('knowledge_install_failed:'+type(error).__name__) from None

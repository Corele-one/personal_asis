#!/usr/bin/env python3
"""Activate the WuCai addition after actual-SDK preflight, with a private rollback."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time


ROOT = Path('/home/mac/astrbot/data/wucai-cli-stage')
PLUGIN = Path('/home/mac/astrbot/data/plugins/astrbot_plugin_life_agent')
CONFIG = Path('/home/mac/astrbot/data/config/astrbot_plugin_life_agent_config.json')
PYTHON = '/home/mac/.local/share/uv/tools/astrbot/bin/python'
FILES = ('main.py', 'metadata.yaml', '_conf_schema.json', 'wucai_cli.py', 'wucai_fulltext.py', 'wucai_chat.py')


def run(*args):
    return subprocess.run(args, capture_output=True, text=True, check=True)


def private_json(path, data):
    fd, temporary = tempfile.mkstemp(prefix='.wucai-config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    os.umask(0o077)
    for name in (*FILES, 'validate-life-sdk.py'):
        if (ROOT / name).is_symlink() or not (ROOT / name).is_file():
            raise ValueError('missing_release_file')
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    for name in (*FILES, 'validate-life-sdk.py'):
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != manifest[name]:
            raise ValueError('release_hash_mismatch')
    if 'version: v2.10.1' not in (ROOT / 'metadata.yaml').read_text():
        raise ValueError('unexpected_version')
    cfg = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if not cfg.get('owner_id') or not cfg.get('owner_platform'):
        raise ValueError('owner_binding_required')
    # No network calls, real provider calls or messages in the installed-SDK fixture.
    with tempfile.TemporaryDirectory(prefix='asis-wucai-preflight-') as tmp:
        target = Path(tmp) / PLUGIN.name
        shutil.copytree(PLUGIN, target)
        for name in FILES:
            shutil.copyfile(ROOT / name, target / name)
        try:
            check = run(PYTHON, str(ROOT / 'validate-life-sdk.py'), tmp)
            print(check.stdout.strip().splitlines()[-1], flush=True)
        except subprocess.CalledProcessError as error:
            print(error.stderr[-6000:], file=sys.stderr)
            raise
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = Path('/home/mac/astrbot/plugin_backups') / ('wucai-' + stamp)
    backup.mkdir(mode=0o700)
    shutil.copytree(PLUGIN, backup / PLUGIN.name)
    shutil.copyfile(CONFIG, backup / CONFIG.name)
    (backup / CONFIG.name).chmod(0o600)
    rollback = ('#!/bin/sh\nset -eu\nsudo systemctl stop astrbot.service\n'
                f'cp -a {backup / PLUGIN.name}/. {PLUGIN}/\n'
                f'if [ ! -f {backup / PLUGIN.name / "wucai_cli.py"} ]; then rm -f {PLUGIN / "wucai_cli.py"}; fi\n'
                f'if [ ! -f {backup / PLUGIN.name / "wucai_fulltext.py"} ]; then rm -f {PLUGIN / "wucai_fulltext.py"}; fi\n'
                f'if [ ! -f {backup / PLUGIN.name / "wucai_chat.py"} ]; then rm -f {PLUGIN / "wucai_chat.py"}; fi\n'
                f'cp {backup / CONFIG.name} {CONFIG}\nchmod 600 {CONFIG}\n'
                'sudo systemctl start astrbot.service\n')
    (backup / 'rollback.sh').write_text(rollback)
    (backup / 'rollback.sh').chmod(0o700)
    try:
        run('sudo', 'systemctl', 'stop', 'astrbot.service')
        life = Path('/home/mac/.local/share/personal-asis-life/life.sqlite3')
        with sqlite3.connect(life.as_uri() + '?mode=ro', uri=True) as src:
            with sqlite3.connect(backup / 'life-before.sqlite3') as dst:
                src.backup(dst)
        (backup / 'life-before.sqlite3').chmod(0o600)
        for name in FILES:
            shutil.copyfile(ROOT / name, PLUGIN / name)
            (PLUGIN / name).chmod(0o644)
        cfg['wucai_enabled'] = True
        private_json(CONFIG, cfg)
        since = datetime.now().astimezone().isoformat(timespec='seconds')
        run('sudo', 'systemctl', 'start', 'astrbot.service')
        # The existing 1 GiB VPS can spend minutes paging while AstrBot imports.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            journal = subprocess.run(['journalctl', '-u', 'astrbot.service', '--since', since,
                '--no-pager', '-o', 'cat', '--grep', '(?i)added llm tool: wucai_read'],
                capture_output=True, text=True)
            if 'added llm tool: wucai_read' in journal.stdout.lower():
                break
            if subprocess.run(['systemctl', 'is-active', '--quiet', 'astrbot.service']).returncode:
                raise RuntimeError('service_inactive')
            time.sleep(1)
        else:
            raise RuntimeError('wucai_tool_registration_not_confirmed')
        run('systemctl', 'is-active', 'astrbot.service')
        for name in FILES:
            if hashlib.sha256((PLUGIN / name).read_bytes()).hexdigest() != manifest[name]:
                raise RuntimeError('installed_hash_mismatch')
    except BaseException:
        subprocess.run(['sh', str(backup / 'rollback.sh')], check=True)
        raise
    print(json.dumps(dict(plugin_version='2.10.1', wucai_enabled=True,
        sdk_preflight='passed', service='active', wucai_tool_registration='confirmed',
        files_verified=len(FILES), backup=str(backup))))


if __name__ == '__main__':
    main()

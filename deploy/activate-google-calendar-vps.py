#!/usr/bin/env python3
"""Deploy only the guarded Calendar capability into the existing Life plugin."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time


ROOT = Path('/home/mac/astrbot/data/google-calendar-mcp')
PLUGIN = Path('/home/mac/astrbot/data/plugins/astrbot_plugin_life_agent')
CONFIG = Path('/home/mac/astrbot/data/config/astrbot_plugin_life_agent_config.json')
PYTHON = Path('/home/mac/.local/share/uv/tools/astrbot/bin/python')
FILES = ('main.py', 'metadata.yaml', '_conf_schema.json')


def run(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, capture_output=capture, text=True)


def write_private_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix='.calendar-config-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        os.chmod(path, 0o600)
    finally:
        Path(name).unlink(missing_ok=True)


def main(stage_arg: str) -> None:
    os.umask(0o077)
    stage = Path(stage_arg).resolve()
    if not stage.is_relative_to((ROOT / 'staging').resolve()):
        raise ValueError('unexpected_stage')
    for name in (*FILES, 'validate-life-sdk.py'):
        path = stage / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('release_file_missing_or_unsafe')
    if 'version: v2.7.0' not in (stage / 'metadata.yaml').read_text(encoding='utf-8'):
        raise ValueError('unexpected_plugin_version')
    if not CONFIG.is_file() or not PLUGIN.is_dir():
        raise ValueError('existing_life_plugin_required')

    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if not config.get('owner_platform') or not config.get('owner_id'):
        raise ValueError('existing_owner_binding_required')
    config['google_calendar_enabled'] = True
    config.setdefault('google_calendar_write_enabled', False)

    private = ROOT
    credentials = private / 'gcp-oauth.keys.json'
    tokens = private / 'tokens.json'
    token_data = json.loads(tokens.read_text(encoding='utf-8'))['normal']
    scope = 'https://www.googleapis.com/auth/calendar.readonly'
    if (credentials.stat().st_mode & 0o777) != 0o600 or (tokens.stat().st_mode & 0o777) != 0o600:
        raise ValueError('oauth_files_must_be_0600')
    if scope not in set(str(token_data.get('scope', '')).split()) or not token_data.get('refresh_token'):
        raise ValueError('readonly_oauth_token_required')

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    preflight_root = private / 'preflight' / stamp
    preflight_plugin = preflight_root / 'astrbot_plugin_life_agent'
    preflight_root.mkdir(mode=0o700, parents=True)
    shutil.copytree(PLUGIN, preflight_plugin)
    for name in FILES:
        shutil.copyfile(stage / name, preflight_plugin / name)
    try:
        check = run(str(PYTHON), str(stage / 'validate-life-sdk.py'), str(preflight_root))
        print(check.stdout.strip().splitlines()[-1], flush=True)
    except subprocess.CalledProcessError as error:
        print((error.stdout or '')[-2000:], file=sys.stderr)
        print((error.stderr or '')[-4000:], file=sys.stderr)
        raise
    finally:
        shutil.rmtree(preflight_root, ignore_errors=True)

    backup_root = Path('/home/mac/astrbot/plugin_backups')
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = backup_root / f'google-calendar-{stamp}'
    backup.mkdir(mode=0o700)
    shutil.copytree(PLUGIN, backup / 'astrbot_plugin_life_agent')
    shutil.copyfile(CONFIG, backup / CONFIG.name)
    (backup / CONFIG.name).chmod(0o600)

    try:
        service_since = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        run('sudo', 'systemctl', 'stop', 'astrbot.service')
        for name in FILES:
            shutil.copyfile(stage / name, PLUGIN / name)
            (PLUGIN / name).chmod(0o644)
        write_private_json(CONFIG, config)
        run('sudo', 'systemctl', 'start', 'astrbot.service')
        run('sudo', 'systemctl', 'is-active', 'astrbot.service')

        marker = 'life_agent Google Calendar MCP connected with 7 read-only tools'
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            result = subprocess.run(
                ['journalctl', '-u', 'astrbot.service', '--since', service_since, '--no-pager',
                 '-o', 'cat', '--grep', marker],
                capture_output=True, text=True,
            )
            if result.returncode == 0 and marker in result.stdout:
                break
            if subprocess.run(['systemctl', 'is-active', '--quiet', 'astrbot.service']).returncode != 0:
                raise RuntimeError('astrbot_service_not_active')
            time.sleep(2)
        else:
            raise RuntimeError('calendar_mcp_startup_not_confirmed')
        if (tokens.stat().st_mode & 0o777) != 0o600:
            raise RuntimeError('oauth_token_permissions_changed')
    except BaseException:
        subprocess.run(['sudo', 'systemctl', 'stop', 'astrbot.service'], check=False)
        shutil.rmtree(PLUGIN)
        shutil.copytree(backup / 'astrbot_plugin_life_agent', PLUGIN)
        shutil.copyfile(backup / CONFIG.name, CONFIG)
        CONFIG.chmod(0o600)
        subprocess.run(['sudo', 'systemctl', 'start', 'astrbot.service'], check=False)
        raise

    print(json.dumps({
        'plugin_version': '2.7.0',
        'google_calendar_enabled': True,
        'google_calendar_write_enabled': config['google_calendar_write_enabled'],
        'private_chat_gate_sdk_preflight': 'passed',
        'mcp_startup': 'confirmed',
        'oauth_scope': 'calendar.readonly',
        'backup': str(backup),
    }))


if __name__ == '__main__':
    main(sys.argv[1])

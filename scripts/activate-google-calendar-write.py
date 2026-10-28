#!/usr/bin/env python3
"""Enable the guarded Calendar write proposal tools after OAuth re-consent."""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


PRIVATE = Path('/home/mac/astrbot/data/google-calendar-mcp')
CONFIG = Path('/home/mac/astrbot/data/config/astrbot_plugin_life_agent_config.json')
PLUGIN = Path('/home/mac/astrbot/data/plugins/astrbot_plugin_life_agent')
BACKUPS = Path('/home/mac/astrbot/plugin_backups')
EXPECTED_SCOPES = {
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events.owned',
}


def atomic_json(path: Path, value: dict) -> None:
    fd, name = tempfile.mkstemp(prefix='.calendar-write-config-', dir=path.parent)
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


def wait_marker(since: str, marker: str, timeout: int = 180) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ['journalctl', '-u', 'astrbot.service', '--since', since, '--no-pager', '-o', 'cat', '--grep', marker],
            capture_output=True, text=True)
        if result.returncode == 0 and marker in result.stdout:
            return True
        if subprocess.run(['systemctl', 'is-active', '--quiet', 'astrbot.service']).returncode != 0:
            return False
        time.sleep(2)
    return False


def main() -> None:
    os.umask(0o077)
    if PRIVATE.is_symlink() or CONFIG.is_symlink() or PLUGIN.is_symlink():
        raise RuntimeError('calendar_write_paths_must_not_be_symlinks')
    if (PRIVATE.stat().st_mode & 0o777) != 0o700:
        raise RuntimeError('calendar_private_directory_must_be_0700')
    tokens_path = PRIVATE / 'tokens.json'
    client_path = PRIVATE / 'gcp-oauth.keys.json'
    if any(path.is_symlink() or not path.is_file() or (path.stat().st_mode & 0o777) != 0o600
           for path in (tokens_path, client_path)):
        raise RuntimeError('oauth_files_must_be_private_0600')
    token = json.loads(tokens_path.read_text(encoding='utf-8'))['normal']
    scopes = set(str(token.get('scope', '')).split())
    if scopes != EXPECTED_SCOPES or not token.get('refresh_token'):
        raise RuntimeError('exact_calendar_read_and_owned_event_scopes_required')
    if 'version: v2.7.0' not in (PLUGIN / 'metadata.yaml').read_text(encoding='utf-8'):
        raise RuntimeError('life_plugin_v2_7_0_required')

    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    if not (config.get('google_calendar_enabled') and config.get('owner_platform') and config.get('owner_id')):
        raise RuntimeError('existing_calendar_read_and_owner_binding_required')
    if config.get('google_calendar_write_enabled') is True:
        raise RuntimeError('calendar_writes_are_already_enabled')

    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup_dir = BACKUPS / f'google-calendar-write-{stamp}'
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    shutil.copyfile(CONFIG, backup_dir / CONFIG.name)
    (backup_dir / CONFIG.name).chmod(0o600)
    config['google_calendar_write_enabled'] = True

    try:
        since = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
        atomic_json(CONFIG, config)
        subprocess.run(['sudo', 'systemctl', 'restart', 'astrbot.service'], check=True, capture_output=True, text=True)
        subprocess.run(['systemctl', 'is-active', 'astrbot.service'], check=True, capture_output=True, text=True)
        marker = 'life_agent Google Calendar write proposals enabled with per-operation confirmation'
        if not wait_marker(since, marker):
            raise RuntimeError('calendar_write_startup_not_confirmed')
    except BaseException:
        previous = json.loads((backup_dir / CONFIG.name).read_text(encoding='utf-8'))
        atomic_json(CONFIG, previous)
        subprocess.run(['sudo', 'systemctl', 'restart', 'astrbot.service'], check=False, capture_output=True, text=True)
        raise

    print(json.dumps({
        'google_calendar_write_enabled': True,
        'scope': 'calendar.readonly + calendar.events.owned',
        'confirmation_flow': 'owner private chat, exact code, five-minute expiry, one use',
        'backup': str(backup_dir),
    }))


if __name__ == '__main__':
    main()

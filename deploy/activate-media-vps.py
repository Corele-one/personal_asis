"""Narrow activation: preserve existing providers, plugins, life state, and units."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

PYTHON = '/home/mac/.local/share/uv/tools/astrbot/bin/python'
DATA = Path('/home/mac/astrbot/data')
NAME = 'astrbot_plugin_media_agent'


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True)


def main():
    os.umask(0o077)
    stage = Path(sys.argv[1]).resolve()
    if not stage.is_relative_to(Path('/home/mac/personal-asis-media-incoming')):
        raise ValueError('unexpected_stage')
    manifest = json.loads((stage / 'manifest.json').read_text())
    for name, expected in manifest.items():
        path = stage / name
        if path.is_symlink() or not path.resolve().is_relative_to(stage) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('release_integrity_failed')
    for name in ('pdfinfo','pdftotext','pdftoppm','tesseract','ffmpeg','ffprobe'):
        if not shutil.which(name):
            raise ValueError('required_system_dependency_missing')
    langs = run('tesseract','--list-langs').stdout.split()
    if not {'chi_sim','eng'}.issubset(langs):
        raise ValueError('ocr_language_missing')
    try:
        preflight = run(PYTHON, str(stage / 'validate-media-sdk.py'), str(stage))
    except subprocess.CalledProcessError as error:
        print(error.stderr[-5000:], file=sys.stderr)
        raise
    print(preflight.stdout.strip().splitlines()[-1], flush=True)
    binding = json.loads((DATA / 'config/astrbot_plugin_life_agent_config.json').read_text(encoding='utf-8-sig'))
    config = dict(enabled=True, owner_platform=binding.get('owner_platform'), owner_id=binding.get('owner_id'),
                  audio_backend='groq_whisper')
    if not config['owner_platform'] or not config['owner_id']:
        raise ValueError('existing_owner_binding_required')
    cfgpath = DATA / 'config' / (NAME + '_config.json')
    if cfgpath.exists():
        oldcfg = json.loads(cfgpath.read_text(encoding='utf-8-sig'))
        if (oldcfg.get('owner_platform'),oldcfg.get('owner_id')) != (config['owner_platform'],config['owner_id']):
            raise ValueError('existing_binding_changed')
    credential = DATA / 'whisper/groq.key'
    authorization = DATA / 'whisper/authorization.json'
    if (not credential.is_file() or credential.is_symlink() or credential.stat().st_mode & 0o077
        or not authorization.is_file()):
        raise ValueError('owner_authorized_private_whisper_credential_required')
    consent = json.loads(authorization.read_text())
    identity = hashlib.sha256(json.dumps([config['owner_platform'],config['owner_id']]).encode()).hexdigest()
    if (consent.get('provider') != 'groq' or not consent.get('owner_authorized_audio_upload')
        or consent.get('owner_binding_sha256') != identity):
        raise ValueError('explicit_groq_audio_authorization_required')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup = Path('/home/mac/astrbot/plugin_backups') / ('media-' + stamp)
    backup.mkdir(mode=0o700)
    plugin = DATA / 'plugins' / NAME
    if plugin.exists():
        shutil.copytree(plugin, backup / NAME)
    if cfgpath.exists():
        shutil.copyfile(cfgpath, backup / cfgpath.name)
    life_main = DATA / 'plugins/astrbot_plugin_life_agent/main.py'
    shutil.copyfile(life_main, backup / 'life-agent-main.py')
    rollback = ('#!/bin/sh\nset -eu\nsudo systemctl stop astrbot.service\n'
        f'rm -rf {plugin}\n' + (f'cp -a {backup / NAME} {plugin}\n' if plugin.exists() else '')
        + (f'cp {backup / cfgpath.name} {cfgpath}\nchmod 600 {cfgpath}\n' if cfgpath.exists() else f'rm -f {cfgpath}\n')
        + f'cp {backup / "life-agent-main.py"} {life_main}\n'
        + 'sudo systemctl start astrbot.service\n')
    (backup / 'rollback.sh').write_text(rollback)
    (backup / 'rollback.sh').chmod(0o700)
    before_config = hashlib.sha256((DATA/'cmd_config.json').read_bytes()).hexdigest()
    try:
        run('sudo','systemctl','stop','astrbot.service')
        if plugin.exists():
            shutil.rmtree(plugin)
        shutil.copytree(stage / NAME, plugin)
        cfgpath.write_text(json.dumps(config))
        cfgpath.chmod(0o600)
        # Remove just the now-stale status sentence; do not redeploy unrelated Life edits.
        text = life_main.read_text()
        if text.count('附件识别未接入。') > 1:
            raise ValueError('unexpected_life_status_text')
        life_main.write_text(text.replace('附件识别未接入。', ''))
        since = datetime.now().astimezone().isoformat(timespec='seconds')
        run('sudo','systemctl','start','astrbot.service')
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            logs = subprocess.run(['journalctl','-u','astrbot.service','--since',since,'--no-pager','-o','cat',
                '--grep','(?i)added llm tool: attachment_'], capture_output=True, text=True)
            # journalctl --grep returns 1 for an empty match set during startup.
            if logs.returncode not in (0, 1):
                raise RuntimeError('journal_query_failed')
            journal = logs.stdout.lower()
            if all('added llm tool: ' + name in journal for name in ('attachment_media','attachment_send_result')):
                break
            run('systemctl','is-active','astrbot.service')
            time.sleep(1)
        else:
            raise RuntimeError('media_tools_not_registered')
        if hashlib.sha256((DATA/'cmd_config.json').read_bytes()).hexdigest() != before_config:
            raise RuntimeError('unexpected_astrbot_config_change')
        for name, expected in manifest.items():
            if name.startswith(NAME + '/') and hashlib.sha256((plugin / name.split('/',1)[1]).read_bytes()).hexdigest() != expected:
                raise RuntimeError('installed_hash_mismatch')
        run('systemctl','is-active','personal-asis-dashboard.service')
    except BaseException:
        run('sh',str(backup/'rollback.sh'))
        raise
    print(json.dumps(dict(plugin_version='1.1.1', backup=str(backup), tools_registered=2,
        service='active', existing_provider_configuration='unchanged', real_model_calls=0, real_messages_sent=0)))


if __name__ == '__main__':
    main()

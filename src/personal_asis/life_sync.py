"""Pull life events at Pi startup; show the exact local edits before any vault write."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import date
from .native_sources import HOME, PROFILE, private_write, source_configuration

REMOTE_EXPORT = 'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.life_export'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def pull(config, state):
    host = config['host']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+', host):
        raise ValueError('invalid_ssh_host')
    port = config.get('port', 22)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid_ssh_port')
    # Bounded batch, no model calls, remote shell receives a fixed command only.
    for _ in range(10):
        result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5',
            '-o', 'ConnectionAttempts=1', '-p', str(port), host, REMOTE_EXPORT],
            input=json.dumps({'after': state['cursor']}), capture_output=True, text=True, timeout=12)
        if result.returncode:
            raise ValueError('vps_sync_unavailable')
        if len(result.stdout.encode()) > 5_000_000:
            raise ValueError('sync_response_too_large')
        batch = json.loads(result.stdout)
        if batch.get('version') != 1 or not isinstance(batch.get('changes'), list) or len(batch['changes']) > 200:
            raise ValueError('invalid_sync_protocol')
        cursor = state['cursor']
        for change in batch['changes']:
            seq, record = change['seq'], change['record']
            if type(seq) is not int or seq <= cursor:
                raise ValueError('invalid_sync_sequence')
            validate_record(record)
            state['records'][record['id']] = record
            cursor = seq
        if batch['cursor'] != cursor:
            raise ValueError('invalid_sync_cursor')
        state['cursor'] = cursor
        if len(batch['changes']) < 200:
            return


def validate_record(r):
    if not re.fullmatch('[a-f0-9]{64}', r.get('id', '')) or type(r.get('revision')) is not int or r['revision'] < 1:
        raise ValueError('invalid_record_identity')
    if date.fromisoformat(r['day']).isoformat() != r['day']:
        raise ValueError('invalid_record_day')
    if type(r.get('deleted')) is not bool or r['kind'] not in ('journal','health','sleep_bed','sleep_wake','task'):
        raise ValueError('invalid_record')
    for key, limit in (('text',16000),('summary',4000),('occurred_at',80)):
        if (not isinstance(r.get(key), str) or len(r[key].encode()) > limit
                or any(ord(c) < 32 and c not in '\n\r\t' for c in r[key])):
            raise ValueError('invalid_record_body')


def block(r):
    quote = lambda s: '\n'.join('> ' + line for line in s.replace('\r', '').split('\n'))
    text = f"<!-- astrbot:{r['id']}:start -->\n### {r['occurred_at']} · {r['kind']}\n\n"
    text += quote(r['text']) + '\n'
    if r['summary']:
        text += '\nAstrBot 整理（可修正）：\n' + quote(r['summary']) + '\n'
    if r.get('due_at'):
        text += '\n时间节点：' + r['due_at'] + '；状态：' + r['task_status'] + '\n'
    return text + f"<!-- astrbot:{r['id']}:end -->\n"


def safe_target(root, relative):
    root = Path(root)
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise ValueError('daily_path_outside_life')
    if root.is_symlink() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('daily_symlink_denied')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('daily_path_outside_life')
    return path


def plan(state, root, daily):
    changes, files = [], {}
    def load(relative):
        target = safe_target(root, relative)
        if relative not in files:
            raw = target.read_bytes() if target.exists() else b''
            if len(raw) > 2_000_000:
                raise ValueError('daily_file_too_large')
            files[relative] = dict(path=target, before=raw, after=raw.decode('utf-8'))
        return files[relative]
    for rid, r in state['records'].items():
        old = state['applied'].get(rid)
        if old and old['revision'] == r['revision']:
            continue
        relative = str(Path(daily) / (r['day'] + '.md'))
        targets = list(dict.fromkeys([old['path'], relative] if old else [relative]))
        pattern = re.compile(r'^<!-- astrbot:' + rid + r':start -->\n.*?^<!-- astrbot:' + rid + r':end -->\n?', re.M | re.S)
        for rel in targets:
            f = load(rel)
            matches = list(pattern.finditer(f['after']))
            if len(matches) > 1:
                raise ValueError('duplicate_sync_blocks')
            if rel == relative and not r['deleted']:
                rendered = block(r)
                if matches:
                    f['after'] = pattern.sub(lambda _: rendered, f['after'])
                else:
                    heading = re.search(r'^## AstrBot 同步[ \t]*$', f['after'], re.M)
                    if heading:
                        following = re.search(r'^## ', f['after'][heading.end():], re.M)
                        pos = heading.end() + following.start() if following else len(f['after'])
                        f['after'] = f['after'][:pos].rstrip() + '\n\n' + rendered + '\n' + f['after'][pos:]
                    else:
                        f['after'] = f['after'].rstrip() + '\n\n## AstrBot 同步\n\n' + rendered
            elif matches:
                f['after'] = pattern.sub('', f['after'])
        changes.append((rid, dict(revision=r['revision'], path=relative)))
    return [f for f in files.values() if f['before'] != f['after'].encode()], changes


def apply(files):
    # Recheck the entire batch before writing; also recheck each file at replacement.
    for f in files:
        if (f['path'].read_bytes() if f['path'].exists() else b'') != f['before']:
            raise ValueError('daily_changed_reconfirmation_required')
    for f in files:
        safe_target(f['path'].parent, f['path'].name)
        if (f['path'].read_bytes() if f['path'].exists() else b'') != f['before']:
            raise ValueError('daily_changed_reconfirmation_required')
        f['path'].parent.mkdir(parents=True, exist_ok=True)
        mode = f['path'].stat().st_mode & 0o777 if f['path'].exists() else 0o600
        private_write(f['path'], f['after'])
        f['path'].chmod(mode)


def startup(home=HOME, profile=PROFILE, *, interactive=None):
    profile = Path(profile)
    config_path = profile / 'life-sync.json'
    if not config_path.exists():
        return 'not_configured'
    config = json.loads(config_path.read_text())
    if not config.get('enabled', False):
        return 'disabled'
    interactive = sys.stdin.isatty() and sys.stdout.isatty() if interactive is None else interactive
    # RPC/JSON/noninteractive Pi must never consume an approval from piped input.
    if not interactive:
        return 'interactive_sync_required'
    lock_path = profile / 'life-sync.lock'
    with lock_path.open('a') as lock:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'sync_already_running'
        cache = profile / 'life-sync-cache.json'
        state = json.loads(cache.read_text()) if cache.exists() else dict(cursor=0, records={}, applied={})
        try:
            pull(config, state)
        except (OSError, ValueError, subprocess.SubprocessError):
            print('AstrBot 暂时无法同步；保留待同步内容，下次重试。')
            return 'offline'
        private_write(cache, json.dumps(state, ensure_ascii=False))
        _, sources = source_configuration(home)
        life = sources['life']
        daily = config.get('daily_directory', 'Calendar/Journal/Daily')
        # Source exclusions also constrain the designated write directory.
        from .config import load_config
        source = next(s for s in load_config(Path(home) / 'sources.yaml').sources if s.id == 'life')
        root = Path(life['root'])
        files, changes = plan(state, root, daily)
        for f in files:
            if source.excludes(f['path'].relative_to(root).as_posix()):
                raise ValueError('daily_target_excluded')
        if not changes:
            publish_status(config, state, sources, home=home)
            print('AstrBot：没有新的待同步记录。')
            return 'up_to_date'
        import difflib
        print(f'\nAstrBot：{len(changes)} 条新增／修订记录，以下为完整写入预览（北京时间日期）。')
        for f in files:
            print('\n目标：' + str(f['path']))
            print(''.join(difflib.unified_diff(f['before'].decode().splitlines(True), f['after'].splitlines(True), fromfile='写入前', tofile='确认后')), end='')
        answer = input('\n确认将以上整批内容写入 Obsidian？输入“确认写入”，其他输入跳过：')
        if answer != '确认写入':
            publish_status(config, state, sources, home=home)
            print('已跳过；下次启动 Pi 仍会询问。')
            return 'skipped'
        current = next(s for s in load_config(Path(home) / 'sources.yaml').sources if s.id == 'life')
        if not current.index or current.root != root or any(current.excludes(f['path'].relative_to(root).as_posix()) for f in files):
            raise ValueError('life_source_changed_reconfirmation_required')
        apply(files)
        for rid, receipt in changes:
            state['applied'][rid] = receipt
        private_write(cache, json.dumps(state, ensure_ascii=False))
        publish_status(config, state, sources, home=home)
        print('已写入 Obsidian。')
        return 'applied'


def publish_status(config, state, sources, *, now=None, home=HOME):
    from datetime import datetime, timezone
    pending = sum(state['applied'].get(k,{}).get('revision') != r['revision'] for k,r in state['records'].items())
    value = dict(checked_at=now or datetime.now(timezone.utc).isoformat(),pending=pending,
        applied=len(state['applied']),sources=dict(study='study' in sources,life='life' in sources,
        wucai='reading_wucai' in sources,xiaohongshu=bool(__import__('personal_asis.native_sources',fromlist=['xhs_configuration']).xhs_configuration(home))))
    try:
        subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-p',str(config.get('port',22)),config['host'],
            'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.life_status'],
            input=json.dumps(value),capture_output=True,text=True,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError):
        print('Mac 状态暂未上传；不影响已确认的本机同步。')


def main():
    parser = argparse.ArgumentParser(description='交互预览并确认 AstrBot → Obsidian 同步')
    parser.parse_args()
    try:
        return 0 if startup() not in ('offline',) else 1
    except (OSError, ValueError, KeyError) as error:
        print('AstrBot 同步停止：' + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Explicitly sync life events; show the exact local edits before any vault write."""
import argparse
import difflib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo
from .native_sources import HOME, PROFILE, private_write, source_configuration
from . import life_freewrite as freewrite

REMOTE_EXPORT = 'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.life_export'
PROJECTION_VERSION = 4
TZ = ZoneInfo('Asia/Shanghai')
HEADINGS = r'## (?:随手记|AstrBot 同步)[ \t]*'
MARKER = re.compile(r'<!-- (?:astrbot:[a-f0-9]{64}|asis-(?:habits|learning):\d{4}-\d{2}-\d{2}):(?:start|end) -->')


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
    if local_time(r['occurred_at']).date().isoformat() != r['day']:
        raise ValueError('record_day_mismatch')
    if 'tracking' in r:
        from .life_tracking import validate
        validate(r['tracking'], r['text'])


def block(r):
    return freewrite.block(r)


def local_time(value):
    at = datetime.fromisoformat(value)
    if at.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return at.astimezone(TZ)


def sleep_only(r):
    return freewrite.sleep_only(r)


def projected(r):
    return freewrite.omission(r) is None


def current_receipt(r, old):
    return (old is not None and old['revision'] == r['revision']
            and old.get('projection') == PROJECTION_VERSION
            and old.get('present') == projected(r))


def remove_empty_heading(text):
    return freewrite.clean(text)


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


def plan(state, root, daily, **kwargs):
    from .life_journal import plan as journal_plan
    return journal_plan(state,root,daily,**kwargs)

def preview_ranges(lines, ranges, owned=()):
    """Expand diff fragments into complete records, then merge nearby fragments."""
    blocks, opened = list(owned), {}
    for index, line in enumerate(lines):
        if not MARKER.fullmatch(line):
            continue
        identity, edge = line[5:-4].rsplit(':', 1)
        if edge == 'start':
            opened[identity] = index
        elif identity in opened:
            blocks.append((opened.pop(identity), index + 1))
    expanded = []
    for start, end in ranges:
        if start == end:
            containing = next(((a, b) for a, b in blocks if a <= start <= b), None)
            if containing is None:
                continue
            start, end = containing
        for a, b in blocks:
            if start < b and a < end:
                start, end = min(start, a), max(end, b)
        expanded.append((start, end))
    merged = []
    for start, end in sorted(expanded):
        if merged and (start <= merged[-1][1] or not any(lines[merged[-1][1]:start])):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def preview(files, *, raw=False):
    """Show complete changed records, all other edits, and their section context."""
    for f in sorted(files, key=lambda f: str(f['path'])):
        print(f"\n  {f['path'].stem} · {'更新' if f['before'] else '新建'}")
        print('  ' + str(f['path']))
        before_text, after_text = f['before'].decode(), f['after']
        if raw:
            print(''.join(difflib.unified_diff(before_text.splitlines(True), after_text.splitlines(True),
                                             fromfile='写入前', tofile='确认后')), end='')
            continue
        # Ignore line-ending-only churn here; raw diff retains the exact bytes.
        before, after = before_text.splitlines(), after_text.splitlines()
        matcher = difflib.SequenceMatcher(a=before, b=after)
        edits = [op for op in matcher.get_opcodes() if op[0] != 'equal']
        for label, lines, ranges in (
                ('移除', before, [(i, j) for _, i, j, _, _ in edits]),
                ('写入', after, [(k, l) for _, _, _, k, l in edits])):
            locs = f.get('owned_before' if label == '移除' else 'owned_after',{}).values()
            original = before_text if label == '移除' else after_text
            owned = [(original[:v['start']].count('\n'), original[:v['start']].count('\n')+len(v['text'].splitlines())) for v in locs]
            for start, end in preview_ranges(lines, ranges, owned):
                visible = [line for line in lines[start:end] if not MARKER.fullmatch(line)]
                if not any(line.strip() for line in visible):
                    continue
                context = {}
                for _, _, level, title in freewrite.headings('\n'.join(lines[:start+1])):
                    context = {k:v for k,v in context.items() if k < level}
                    context[level] = title
                scope = ' / '.join(context[level] for level in (3, 4) if level in context)
                print('\n  ' + label + (' · ' + scope if scope else ''))
                for line in visible:
                    print('    ' + line)


def confirm(files, *, raw=False):
    preview(files, raw=raw)
    while True:
        answer = input('\n输入“确认写入”保存以上改动 · d 查看原始 diff · 回车暂不写入\n› ')
        if answer.lower() == 'd':
            preview(files, raw=True)
        else:
            return answer == '确认写入'


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


def startup(home=HOME, profile=PROFILE, *, interactive=None, raw_diff=False, layout_mode=None, retry_layout=False):
    profile = Path(profile)
    config_path = profile / 'life-sync.json'
    if not config_path.exists():
        return 'not_configured'
    config = json.loads(config_path.read_text())
    if not config.get('enabled', False):
        return 'disabled'
    interactive = sys.stdin.isatty() and sys.stdout.isatty() if interactive is None else interactive
    # Never consume a vault-write approval from piped input.
    if not interactive:
        return 'interactive_sync_required'
    def finish(result):
        if config.get('shared_sync_mode','off') == 'off':
            return result
        from .shared_sync import run as sync_shared
        try:
            shared = sync_shared(config, home, profile, interactive=True)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error,subprocess.SubprocessError):
            print('共享库同步未完成；本机资料和已确认日记保留，下次 pi_sync 按游标继续。')
            return 'shared_partial'
        return result if shared == 'complete' else 'shared_partial'
    lock_path = profile / 'life-sync.lock'
    with lock_path.open('a') as lock:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'sync_already_running'
        print('\nPi · 日记同步\n生活自述 → Freewrite；习惯／学习 → 对应栏目。')
        if config.get('shared_sync_mode','off') != 'off':
            print('1/3 · VPS 生活记录 → Mac（写日记仍需本次确认）')
        cache = profile / 'life-sync-cache.json'
        state = json.loads(cache.read_text()) if cache.exists() else dict(cursor=0, records={}, applied={})
        try:
            pull(config, state)
        except (OSError, ValueError, subprocess.SubprocessError):
            print('AstrBot 暂时无法同步；保留待同步内容，下次重试。')
            return finish('offline')
        private_write(cache, json.dumps(state, ensure_ascii=False))
        if config.get('profile_sync_mode', 'off') != 'off':
            from .profile_sync import run as sync_profile
            try:
                sync_profile(config, home, profile, interactive=True)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
                print('本人背景暂未同步；保留现有背景，不影响生活记录预览。')
        _, sources = source_configuration(home)
        life = sources['life']
        daily = config.get('daily_directory', 'Calendar/Journal/Daily')
        # Source exclusions also constrain the designated write directory.
        from .config import load_config
        source = next(s for s in load_config(Path(home) / 'sources.yaml').sources if s.id == 'life')
        root = Path(life['root'])
        from . import life_journal
        if life_journal.recover(state,root):
            private_write(cache,json.dumps(state,ensure_ascii=False))
        mode = layout_mode or config.get('journal_layout_mode', 'smart')
        if mode not in ('smart', 'plain'):
            raise ValueError('invalid_journal_layout_mode')
        from .life_layout import Editor, LayoutUnavailable
        editor = Editor(home,profile,retry=retry_layout) if mode == 'smart' else None
        if editor:
            print('随记会结合当天文字编排；沿用相关段落，必要时补主题标题。')
        try:
            files, changes = plan(state, root, daily, editor=editor,
                                  allowed=lambda relative: not source.excludes(relative))
        except LayoutUnavailable as error:
            print('智能编排暂未完成，本次日记未写入；资料库同步继续。')
            if str(error) == 'layout_call_limit':
                print('本轮已达 4 次编排上限；已完成方案保留，下次 pi_sync 继续。')
            else:
                print('同一输入不会自动重发模型请求；需重试时运行 pi_sync --retry-layout，'
                      '或用 --layout plain 预览原话追加。')
            return finish('layout_unavailable')
        from .life_projection import plan as plan_activity
        files, activity_changes = plan_activity(state, root, daily, files)
        life_journal.seal(files,changes,root)
        for f in files:
            if source.excludes(f['path'].relative_to(root).as_posix()):
                raise ValueError('daily_target_excluded')
        ignored = sum(freewrite.omission(r) not in (None, 'deleted') for r in state['records'].values())
        if ignored:
            print(f'已过滤 {ignored} 条问候、命令、作息、提醒或单独归档的活动记录。')
        if not files:
            # A crash may leave an already-written block without its receipt.
            # Reconcile metadata without asking to approve an empty vault edit.
            for rid, receipt in changes:
                state['applied'][rid] = receipt
            state.setdefault('activity_applied', {}).update(activity_changes)
            private_write(cache, json.dumps(state, ensure_ascii=False))
            publish_status(config, state, sources, home=home)
            print('日记已是最新，本次无需写入。')
            return finish('up_to_date')
        print(f'\n待确认 · {len(files)} 篇日记\n以下按完整段落显示改动。')
        if not confirm(files, raw=raw_diff):
            publish_status(config, state, sources, home=home)
            print('本次未写入。改动已保留，下次 pi_sync 可继续。')
            return finish('skipped')
        current = next(s for s in load_config(Path(home) / 'sources.yaml').sources if s.id == 'life')
        if not current.index or current.root != root or any(current.excludes(f['path'].relative_to(root).as_posix()) for f in files):
            raise ValueError('life_source_changed_reconfirmation_required')
        state['pending_projection'] = life_journal.pending(state,files,changes,activity_changes,root)
        private_write(cache,json.dumps(state,ensure_ascii=False))
        apply(files)
        for rid, receipt in changes:
            state['applied'][rid] = receipt
        state.setdefault('activity_applied', {}).update(activity_changes)
        state.pop('pending_projection',None)
        private_write(cache, json.dumps(state, ensure_ascii=False))
        publish_status(config, state, sources, home=home)
        print(f'已保存到 Obsidian · {len(files)} 篇日记。')
        return finish('applied')


def publish_status(config, state, sources, *, now=None, home=HOME):
    from datetime import datetime, timezone
    pending = sum(not current_receipt(r, state['applied'].get(k))
                  for k, r in state['records'].items()
                  if projected(r) or (k in state['applied'] and state['applied'][k].get('present', True)))
    applied = sum(receipt.get('present', True) and projected(state['records'][rid])
                  for rid, receipt in state['applied'].items() if rid in state['records'])
    value = dict(checked_at=now or datetime.now(timezone.utc).isoformat(),pending=pending,
        applied=applied,sources=dict(study='study' in sources,life='life' in sources,
        wucai='reading_wucai' in sources,xiaohongshu=bool(__import__('personal_asis.native_sources',fromlist=['xhs_configuration']).xhs_configuration(home))))
    try:
        subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5','-p',str(config.get('port',22)),config['host'],
            'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.life_status'],
            input=json.dumps(value),capture_output=True,text=True,timeout=10,check=True)
    except (OSError,subprocess.SubprocessError):
        print('Mac 状态暂未上传；不影响已确认的本机同步。')


def main():
    parser = argparse.ArgumentParser(prog='pi_sync', description='交互预览并确认 AstrBot → Obsidian 同步')
    parser.add_argument('--diff', action='store_true', help='使用完整原始 diff 预览日记改动')
    parser.add_argument('--layout', choices=('smart','plain'), help='结合当天内容编排（默认 smart），或原话追加')
    parser.add_argument('--retry-layout', action='store_true', help='主动重试此前失败或结果未知的编排请求')
    args = parser.parse_args()
    try:
        result = startup(raw_diff=args.diff,layout_mode=args.layout,retry_layout=args.retry_layout)
        messages = dict(not_configured='尚未配置同步。', disabled='同步已停用。',
                        interactive_sync_required='请在交互终端运行 pi_sync，以便预览和确认。',
                        sync_already_running='另一个 pi_sync 正在运行，请稍后再试。')
        if result in messages:
            print(messages[result])
        return 0 if result not in ('offline','shared_partial','layout_unavailable') else 1
    except (EOFError, KeyboardInterrupt):
        print('\n已退出日记同步；未确认的改动保留到下次。')
        return 130
    except (OSError, ValueError, KeyError) as error:
        reason = {
            'daily_changed_reconfirmation_required': '预览后日记有变化，请重新运行并核对。',
            'life_source_changed_reconfirmation_required': 'Life 来源配置有变化，请重新预览。',
            'daily_target_excluded': '目标日记在来源排除范围内，请先检查配置。',
            'daily_symlink_denied': '目标包含符号链接，请检查日记目录。',
            'daily_path_outside_life': '目标超出 Life 目录，请检查同步配置。',
            'damaged_sync_block': '日记中的来源标记不完整，请先核对原文件。',
            'duplicate_sync_blocks': '日记中存在重复来源标记，请先核对原文件。',
            'daily_file_too_large': '目标日记超过本次处理上限。',
            'ambiguous_freewrite_section': '日记中存在重复的 Freewrite／聊天随记标题，请先核对原文件。',
            'journal_text_edited': '上次同步正文已被手动修改；已保留现状，请先核对原文。',
            'journal_text_ambiguous': '同步正文有多个相同副本，无法安全定位；已保留现状。',
            'journal_interrupted_file_edited': '上次写入中断后文件发生变化，请先核对日记与私密收据。',
        }.get(str(error), '未能完成同步，请检查配置与文件访问权限后重试。')
        print('同步已暂停：' + reason, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

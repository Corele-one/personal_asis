"""Explicit profile snapshot and separately confirmed updates during pi_sync."""
import copy
from datetime import date
import difflib
import json
from pathlib import Path
import re
import subprocess

from .personal_profile import validate, render
from .profile_transfer import revision
from .native_sources import private_write

REMOTE = 'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.profile_transfer'


def exchange(config, request):
    host, port = config['host'], config.get('port', 22)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+', host) or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('invalid_profile_ssh_target')
    result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1',
                             '-p', str(port), host, REMOTE], input=json.dumps(request, ensure_ascii=False),
                            capture_output=True, text=True, timeout=12)
    if result.returncode or len(result.stdout.encode()) > 48000:
        raise ValueError('profile_transfer_unavailable')
    response = json.loads(result.stdout)
    if not isinstance(response, dict) or response.get('version') != 1:
        raise ValueError('invalid_profile_response')
    if request['operation'] == 'read':
        if set(response) != {'version', 'hash', 'profile'}:
            raise ValueError('invalid_profile_snapshot')
        if response['profile'] is not None:
            validate(response['profile'])
            if response['profile']['status'] != 'approved':
                raise ValueError('profile_approval_required')
        if response['hash'] != revision(response['profile']):
            raise ValueError('invalid_profile_snapshot_hash')
    elif response != dict(version=1, hash=revision(request['profile']), updated=True):
        raise ValueError('invalid_profile_publication_receipt')
    return response


def sources_changed(value, home):
    from .config import load_config
    sources = {s.id:s for s in load_config(Path(home) / 'sources.yaml').sources if s.index}
    changed, checked = set(), {}
    for fact in value['facts']:
        for cite in fact['citations']:
            identity = (cite['source_id'], cite['relative_path'])
            source = sources.get(cite['source_id'])
            if source is None or source.excludes(cite['relative_path']):
                changed.add(identity);continue
            p = source.root / cite['relative_path']
            if (not p.resolve().is_relative_to(source.root.resolve()) or any(x.is_symlink() for x in (p, *p.parents))
                    or not p.is_file() or p.stat().st_size > 2_000_000):
                changed.add(identity);continue
            if identity not in checked:
                import hashlib
                raw = p.read_bytes()
                checked[identity] = (hashlib.sha256(raw).hexdigest(), len(raw.decode().splitlines()))
            digest, lines = checked[identity]
            if digest != cite['sha256'] or lines < cite['line_end']:
                changed.add(identity)
    return changed


def same_proposal(left, right):
    if left is None or right is None:
        return left is right
    return all(left[k] == right[k] for k in ('version', 'scope', 'prepared_on', 'facts'))


def run(config, home, profile, *, interactive):
    mode = config.get('profile_sync_mode', 'off')
    if not interactive or mode == 'off':
        return 'disabled'
    if mode not in ('check', 'confirm'):
        raise ValueError('invalid_profile_sync_mode')
    profile = Path(profile)
    snapshot = exchange(config, dict(operation='read'))
    cache = profile / 'personal-profile-remote.json'
    private_write(cache, json.dumps(snapshot, ensure_ascii=False))
    current = snapshot['profile']
    if current is None:
        print('本人背景：VPS当前未启用；不会自动恢复旧背景。')
    else:
        changed = sources_changed(current, home)
        print(f"本人背景：VPS保留 {len(current['facts'])} 条已确认摘要；{len(changed)} 处来源需核对。")
        if changed:
            print('本次仅检查来源，尚未更新VPS背景；新摘要仍需单独预览确认。')
    receipt_path = profile / 'personal-profile-sync-receipt.json'
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if receipt and receipt.get('state') in ('sending', 'unknown'):
        if snapshot['hash'] == receipt['desired']:
            receipt['state'] = 'confirmed_after_readback'
            private_write(receipt_path, json.dumps(receipt))
        else:
            print('上次背景更新结果未确认；本次不会自动重发，更新仍需重新预览确认。')
    pending = profile / 'personal-profile-next.json'
    if mode == 'check' or not pending.exists():
        return 'checked'
    if pending.is_symlink() or pending.stat().st_size > 16000:
        raise ValueError('invalid_pending_profile')
    before = pending.read_bytes()
    proposal = validate(json.loads(before))
    if same_proposal(current, proposal):
        print('背景候选与VPS一致，无需重复发布。')
        return 'up_to_date'
    if sources_changed(proposal, home):
        raise ValueError('profile_sources_changed_reconfirmation_required')
    approved = copy.deepcopy(proposal)
    approved.update(status='approved', approved_on=date.today().isoformat())
    validate(approved)
    previous = render(current) if current else '（VPS当前没有本人背景）\n'
    print('\nVPS本人背景更新预览（与Obsidian写入分别确认）：')
    print(''.join(difflib.unified_diff(previous.splitlines(True), render(approved).splitlines(True),
                                      fromfile='VPS当前背景', tofile='确认后背景')), end='')
    print('\n确认后完整背景：\n' + render(approved))
    if input('\n输入“确认更新背景”发布以上整份摘要，其他输入跳过：') != '确认更新背景':
        return 'skipped'
    if pending.is_symlink() or pending.read_bytes() != before or sources_changed(approved, home):
        raise ValueError('profile_changed_reconfirmation_required')
    receipt = dict(state='sending', expected=snapshot['hash'], desired=revision(approved))
    private_write(receipt_path, json.dumps(receipt))
    try:
        exchange(config, dict(operation='replace', expected=snapshot['hash'], profile=approved))
    except (OSError, ValueError, subprocess.SubprocessError):
        receipt['state'] = 'unknown'
        private_write(receipt_path, json.dumps(receipt))
        print('背景更新结果未确认；没有自动重发，下次会先读取VPS版本核对。')
        return 'unknown'
    receipt['state'] = 'confirmed'
    private_write(receipt_path, json.dumps(receipt))
    private_write(cache, json.dumps(dict(version=1, hash=revision(approved), profile=approved), ensure_ascii=False))
    print('已更新VPS本人背景。')
    return 'updated'

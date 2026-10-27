"""Mac source refresh then bounded bidirectional SQLite page replication."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sqlite3

from .shared_store import MAX_BATCH, MAX_RECORD, SharedStore
from .shared_sources import refresh_mac

REMOTE = 'PYTHONPATH=/home/mac/personal-asis-v2/src python3 -m personal_asis.shared_transfer'


def exchange(config, request):
    host, port = config['host'], config.get('port',22)
    if (not re.fullmatch(r'[a-zA-Z0-9_.-]+@[a-zA-Z0-9.-]+', host)
            or type(port) is not int or not 1 <= port <= 65535):
        raise ValueError('shared_invalid_ssh_target')
    result = subprocess.run(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=5',
        '-o','ConnectionAttempts=1','-p',str(port),host,REMOTE],
        input=json.dumps(request,ensure_ascii=False),text=True,capture_output=True,timeout=30)
    if result.returncode or len(result.stdout.encode()) > MAX_BATCH + MAX_RECORD + 4096:
        raise ValueError('shared_transfer_unavailable')
    response = json.loads(result.stdout)
    if (not isinstance(response, dict) or set(response) != {'version','received','head','download'}
            or response['version'] != 1 or type(response['received']) is not int
            or type(response['head']) is not int or response['head'] < 0
            or not request['upload']['cursor'] <= response['received'] <= request['head']):
        raise ValueError('shared_invalid_receipt')
    return response


def replicate(store, config, *, transport=exchange, max_pages=50):
    if store.node != 'mac' or type(max_pages) is not int or not 1 <= max_pages <= 200:
        raise ValueError('shared_invalid_sync_budget')
    uploaded = downloaded = 0
    complete = False
    for page in range(max_pages):
        upload = store.export(store.get_meta('ack:vps', 0))
        head = store.get_meta('sequence', 0)
        after = store.get_meta('received:vps', 0)
        response = transport(config, dict(version=1,after=after,head=head,upload=upload))
        if (set(response) != {'version','received','head','download'} or response['version'] != 1
                or type(response['received']) is not int or not upload['cursor'] <= response['received'] <= head
                or type(response['head']) is not int or response['head'] < after):
            raise ValueError('shared_invalid_receipt')
        if response['download']['cursor'] > response['head']:
            raise ValueError('shared_invalid_head')
        if not response['download']['more'] and response['download']['cursor'] != response['head']:
            raise ValueError('shared_incomplete_head')
        store.receive(response['download'], 'vps')
        with store.db:
            store.set_meta('ack:vps', response['received'])
        uploaded += len(upload['changes'])
        downloaded += len(response['download']['changes'])
        if (not response['download']['more']
                and not store.export(response['received'])['changes']):
            complete = True
            break
    result = dict(complete=complete,pages=page+1,uploaded=uploaded,downloaded=downloaded,
                  checked_at=datetime.now(timezone.utc).isoformat())
    with store.db:
        store.set_meta('last_sync', result)
    return result


def run(config, home, profile, *, interactive):
    mode = config.get('shared_sync_mode','off')
    if not interactive or mode == 'off':
        return 'disabled'
    if mode not in ('text','metadata'):
        raise ValueError('shared_invalid_mode')
    scopes = config.get('shared_sync_scopes')
    if (not isinstance(scopes,dict) or set(scopes) != {'notes','reading'}
            or not isinstance(scopes['notes'],dict) or not isinstance(scopes['reading'],list)):
        raise ValueError('shared_explicit_scope_required')
    if type(config.get('shared_refresh_network',True)) is not bool:
        raise ValueError('shared_invalid_refresh_mode')
    print('\n2/3 · 更新 Mac 数据库（Life／Study／五彩／小红书）')
    with SharedStore(Path(profile)/'shared.sqlite3','mac') as store:
        if not store.get_meta('initial_source_backup'):
            from .shared_store import safe_path
            backup = safe_path(Path(profile)/'shared-source-backup')
            backup.mkdir(exist_ok=True,mode=0o700)
            for relative, name in (('index.sqlite3','index.sqlite3'),('reading-library/library.sqlite3','reading-library.sqlite3')):
                source = safe_path(Path(home)/relative)
                if source.is_file():
                    destination = safe_path(backup/name)
                    src = sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)
                    dest = sqlite3.connect(destination)
                    try:
                        src.backup(dest)
                    finally:
                        dest.close();src.close()
                    destination.chmod(0o600)
            with store.db:
                store.set_meta('initial_source_backup',True)
        refresh = refresh_mac(store,home,mode=mode,network=config.get('shared_refresh_network',True),scope=scopes)
        print(f"资料库已更新 · 笔记变更 {refresh['notes']['changed']}，阅读资料变更 {refresh['reading']['changed']}。")
        omitted = refresh['notes']['omitted'] + refresh['reading']['omitted']
        if omitted:
            print(f'{omitted} 个分块命中共享排除或格式规则，原文保留在 Mac。')
        failed = refresh['platforms']['failed']
        if failed:
            print(f'有 {len(failed)} 个来源本次未能刷新；保留已采集资料，未自动重试。')
        if refresh['unavailable_notes'] or refresh['scope_changed']:
            print('部分笔记根目录不可用或超出已确认共享范围；未扩大共享。')
        print('3/3 · 交换数据库增量（SSH）')
        result = replicate(store, config, max_pages=config.get('shared_max_pages',50))
        print(f"本轮上传 {result['uploaded']} 条变更，拉回 {result['downloaded']} 条变更。")
        if not result['complete']:
            print('本轮达到传输上限，剩余变更留到下次 pi_sync。')
        return 'complete' if result['complete'] and not (failed or refresh['unavailable_notes'] or refresh['scope_changed']) else 'partial'

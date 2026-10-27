"""Fixed SSH page exchange for the shared library. No paths, SQL or commands."""
import json
import os
from pathlib import Path
import sys
import sqlite3
from datetime import datetime, timezone

from .shared_store import MAX_BATCH, MAX_RECORD, SharedStore
from .shared_sources import refresh_vps


def handle(request, home):
    if (not isinstance(request, dict) or set(request) != {'version','after','head','upload'}
            or request['version'] != 1 or type(request['after']) is not int or request['after'] < 0
            or type(request['head']) is not int or request['head'] < 0 or not isinstance(request['upload'],dict)):
        raise ValueError('shared_invalid_exchange')
    with SharedStore(Path(home)/'shared.sqlite3', 'vps') as store:
        if store.get_meta('received:mac', 0) > request['head']:
            raise ValueError('shared_replica_reset_requires_reseed')
        if request['upload'].get('cursor', request['head']+1) > request['head']:
            raise ValueError('shared_invalid_head')
        refresh_vps(store, home)
        head = store.get_meta('sequence', 0)
        if request['after'] > head:
            raise ValueError('shared_replica_reset_requires_reseed')
        received = store.receive(request['upload'], 'mac')
        with store.db:
            store.set_meta('mac_last_received', datetime.now(timezone.utc).isoformat())
            store.set_meta('mac_snapshot',dict(received=received,head=request['head'],complete=received>=request['head']))
        head = store.get_meta('sequence', 0)
        return dict(version=1, received=received, head=head, download=store.export(request['after']))


def main():
    os.umask(0o077)
    try:
        raw = sys.stdin.buffer.read(MAX_BATCH + MAX_RECORD + 4097)
        if len(raw) > MAX_BATCH + MAX_RECORD + 4096:
            raise ValueError('shared_request_too_large')
        result = handle(json.loads(raw), Path.home()/'.local/share/personal-asis-life')
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        print('{"error":"shared_exchange_rejected"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

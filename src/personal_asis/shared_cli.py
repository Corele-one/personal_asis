"""Common searchable library CLI for Mac Pi and the VPS owner tools."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid
import sqlite3
from datetime import datetime, timezone

from .shared_store import SharedStore, identity


def annotate(store, target, title, text, *, key=None, expected=0):
    if not target or len(target) > 250 or not text.strip():
        raise ValueError('shared_invalid_annotation')
    parts = target.split('/')
    if len(parts) != 3 or parts[1] not in ('notes','reading','life'):
        raise ValueError('shared_invalid_annotation_target')
    store.read(*parts)
    key = key or identity(store.node,uuid.uuid4().hex)
    if key and expected == 0:
        try:
            old = store.read(store.node,'annotations',key)
        except ValueError:
            old = None
        if old and all(old['body'][k] == v for k,v in (('locator',target),('title',title),('text',text))):
            return dict(origin=store.node,collection='annotations',id=key,version=old['version'])
    body = dict(source='annotation',account='',locator=target,title=title,text=text,
                url='',part=1,parts=1,hash=hashlib.sha256(text.encode()).hexdigest(),
                attribution='本人明确要求保存的共享补充；不替代来源原文',expires_at=None,
                acquired_at=datetime.now(timezone.utc).isoformat(),coverage='explicit_owner_supplement')
    version = store.put('annotations',key,body,expected=expected)
    return dict(origin=store.node,collection='annotations',id=key,version=version)


def main():
    parser = argparse.ArgumentParser(description='两端共用的派生资料库；不修改原始笔记或平台')
    parser.add_argument('action',choices=['status','search','read','annotate','delete-annotation'])
    parser.add_argument('--db',type=Path)
    parser.add_argument('--node',choices=['mac','vps'],default='mac')
    parser.add_argument('--query',default='')
    parser.add_argument('--source',default='')
    parser.add_argument('--account',default='')
    parser.add_argument('--origin',default='mac')
    parser.add_argument('--collection',default='notes')
    parser.add_argument('--id',default='')
    parser.add_argument('--target',default='')
    parser.add_argument('--title',default='共享补充')
    parser.add_argument('--expected',type=int,default=0)
    args = parser.parse_args()
    if args.db is None:
        if args.node == 'vps':
            args.db = Path.home()/'.local/share/personal-asis-life/shared.sqlite3'
        else:
            from .native_sources import PROFILE
            args.db = PROFILE/'shared.sqlite3'
    try:
        with SharedStore(args.db,args.node) as store:
            if args.action == 'status':
                result = store.status()
            elif args.action == 'search':
                result = dict(results=store.search(args.query,source=args.source,account=args.account))
            elif args.action == 'read':
                result = store.read(args.origin,args.collection,args.id)
            elif args.action == 'annotate':
                import sys
                text = sys.stdin.read(64001)
                result = annotate(store,args.target,args.title,text,key=args.id or None,expected=args.expected)
            else:
                result = dict(version=store.put('annotations',args.id,None,expected=args.expected))
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,sqlite3.Error):
        print('{"error":"shared_library_operation_failed"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

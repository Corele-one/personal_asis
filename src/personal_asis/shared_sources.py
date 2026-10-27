"""Project existing source stores into the common library without credentials."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .shared_store import SharedStore, identity, safe_path
from .data_policy import exclusion_reason


def public_text(text):
    # Remove machine paths from a derived copy, never from the source document.
    text = re.sub(r"(?<![A-Za-z0-9:.])(?:file://|[A-Za-z]:[\\/]|/(?:Users|home)/)[^\s\]\[<>\"')]+",
                  '[本机路径]', text)
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


def public_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return ''
        query = [(key, val) for key, val in parse_qsl(parsed.query)
                 if not re.search(r'token|secret|auth|cookie|signature|api.?key', key, re.I)]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ''))
    except ValueError:
        return ''


def document_bodies(source, locator, title, text, *, account='', url='', attribution='',
                    mode='text', expires_at=None, acquired_at='', coverage='source_snapshot'):
    if exclusion_reason(locator, text):
        return []
    text = public_text(text) if mode == 'text' else ''
    title = public_text(title)[:350]
    locator = public_text(locator)
    # Chunk before transport, retaining stable provenance and a hash of this copy.
    pieces = [text[i:i+12000] for i in range(0, len(text), 12000)] or ['']
    digest = hashlib.sha256(text.encode()).hexdigest()
    return [dict(source=source, account=account, locator=locator, title=title, text=part,
                 url=public_url(url), part=i+1, parts=len(pieces), hash=digest,
                 attribution=attribution, expires_at=expires_at,acquired_at=acquired_at,
                 coverage=coverage) for i, part in enumerate(pieces)]


def replace_scope(store, collection, bodies, *, sources, preserve=()):
    """Only a successfully observed source may withdraw its previously shared rows."""
    seen, changed, omitted = set(preserve), 0, 0
    for body in bodies:
        key = identity(body['source'], body['account'], body['locator'], body['part'])
        old = store.db.execute('SELECT body FROM objects WHERE origin=? AND collection=? AND id=?',
                               (store.node,collection,key)).fetchone()
        if old and old['body']:
            previous = json.loads(old['body'])
            if all(previous.get(k) == v for k,v in body.items() if k != 'acquired_at'):
                # Fresh observation of identical content is not a content change.
                body['acquired_at'] = previous['acquired_at']
        before = store.get_meta('sequence', 0)
        try:
            store.put(collection, key, body)
        except ValueError:
            omitted += 1
            continue
        seen.add(key)
        changed += store.get_meta('sequence', 0) != before
    for row in store.db.execute('SELECT id,body FROM objects WHERE origin=? AND collection=? AND body IS NOT NULL',
                                (store.node, collection)).fetchall():
        body = json.loads(row['body'])
        if body['source'] in sources and row['id'] not in seen:
            store.put(collection, row['id'], None);changed += 1
    return dict(changed=changed, omitted=omitted)


def refresh_platforms(home, *, max_pages=2, scope=None):
    from .reading_library import Library, configured_accounts, sync_wucai, sync_xhs
    allowed = configured_accounts(home)
    if scope is not None:
        allowed = {key:label for key,label in allowed.items() if ':'.join(key) in scope.get('reading',[])}
    if not allowed:
        return dict(accounts=0, failed=[], coverage='not_configured')
    failures = []
    with Library(home) as library:
        if ('wucai', 'cn') in allowed:
            today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
            since, until = (today - timedelta(days=6)).isoformat(), today.isoformat()
            try:
                sync_wucai(library, since, until, max_pages=max_pages, refresh=True)
            except Exception:
                failures.append('wucai:cn')
        for source, account in allowed:
            if source == 'xiaohongshu':
                try:
                    sync_xhs(library, account)
                except Exception:
                    failures.append('xiaohongshu:' + account)
    return dict(accounts=len(allowed), failed=failures,
                coverage='wucai_recent_7_days_bounded; xiaohongshu_visible_favorites_only')


def refresh_mac(store, home, *, mode='text', network=True, scope=None):
    from .config import load_config, root_identity
    from .index import Index
    from .reading_library import Library, configured_accounts
    home = Path(home)
    config = load_config(home/'sources.yaml')
    # Reuse the incremental index and all its source/exclusion/format policies.
    # Do not pass a filtered configuration that would disable unrelated sources.
    with Index(safe_path(home/'index.sqlite3'), config) as index:
        report = index.reconcile()
        ready = {r['source_id'] for r in report['sources'] if r['status'] == 'ready'}
        configured = {s.id:s for s in config.sources}
        permitted = {name for name,s in configured.items() if name in ('life','study')
                     and (scope is None or scope.get('notes',{}).get(name) == root_identity(s.root))}
        withdrawn = {name for name in ('life','study') if name not in permitted or not configured[name].index}
        previous = store.get_meta('note_fingerprints',{})
        bodies, preserve = [], set()
        fingerprints = {key:entry for key,entry in previous.items()
                        if entry.get('source') not in ready | withdrawn}
        for row in index.db.execute('''SELECT d.*,f.text FROM documents d JOIN search_index f ON f.rowid=d.rowid
            WHERE d.active=1 AND d.source_id IN ('life','study') AND lower(d.path) LIKE '%.md' ''').fetchall():
            source = configured[row['source_id']]
            if row['source_id'] not in ready or row['source_id'] not in permitted or source.excludes(row['path']):
                continue
            cache_key = identity(row['source_id'],row['path'])
            fingerprint = identity(row['content_hash'],mode,str(source.root),'source_projection_v2')
            cached = previous.get(cache_key,{})
            if cached.get('hash') == fingerprint and all(store.db.execute(
                    'SELECT 1 FROM objects WHERE origin=? AND collection=? AND id=? AND body IS NOT NULL',
                    ('mac','notes',key)).fetchone() for key in cached.get('keys',[])):
                preserve.update(cached['keys']);fingerprints[cache_key] = cached
                continue
            # Recheck exclusions and file identity after indexing; don't export
            # stale private text if the source changed during this run.
            current = index._current(row)
            if current is None:
                continue
            parts = document_bodies(row['source_id'],row['path'],row['title'],row['text'],mode=mode,
                acquired_at=row['indexed_at'],attribution='本人原始笔记；模板、引用与本人自述需分别理解')
            bodies.extend(parts)
            fingerprints[cache_key] = dict(source=row['source_id'],hash=fingerprint,
                keys=[identity(b['source'],b['account'],b['locator'],b['part']) for b in parts])
        notes = replace_scope(store,'notes',bodies,sources=(ready & {'life','study'}) | withdrawn,preserve=preserve)
        # Preserve fingerprints for offline sources without inferring deletion.
        with store.db:
            store.set_meta('note_fingerprints',fingerprints)
    platforms = refresh_platforms(home,scope=scope) if network else dict(accounts=0,failed=[],coverage='cache_only')
    reading_bodies = []
    allowed = configured_accounts(home)
    if scope is not None:
        allowed = {key:label for key,label in allowed.items() if ':'.join(key) in scope.get('reading',[])}
    path = home/'reading-library/library.sqlite3'
    if path.is_file():
        with Library(home, readonly=True) as library:
            for row in library.db.execute('''SELECT o.*,b.payload FROM observations o JOIN blobs b ON b.hash=o.blob_hash
                JOIN accounts a ON a.source=o.source AND a.account=o.account
                WHERE a.enabled=1 AND o.forgotten=0 AND (o.expires_at IS NULL OR o.expires_at>?)''', (time.time(),)):
                if (row['source'],row['account']) not in allowed:
                    continue
                item = json.loads(row['payload'])
                prose = '\n\n'.join(filter(None, [item['author_text'],
                    *['摘录：'+h['quote']+'\n本人批注：'+h['note'] for h in item['highlights']],
                    '本人页面笔记：'+item['user_note'] if item['user_note'] else '']))
                reading_bodies.extend(document_bodies(row['source'], row['item_id'], item['title'], prose,
                    account=row['account'], url=item['url'], mode=mode, expires_at=row['expires_at'],
                    acquired_at=datetime.fromtimestamp(row['fetched_at'],timezone.utc).isoformat(),coverage=item['content_kind'],
                    attribution=item['content_kind']+'；作者原文、摘录和本人批注分别标明；非完整平台历史'))
    # Platform omissions are not unfavorites. Existing library observations are
    # retained; only explicit forget/expiry/config withdrawal removes shared rows.
    reading = replace_scope(store, 'reading', reading_bodies,
                            sources={'wucai','xiaohongshu'} if path.is_file() or not allowed else set())
    result = dict(notes=notes, reading=reading, platforms=platforms,
                  unavailable_notes=sorted(name for name in permitted if configured[name].index and name not in ready),
                  scope_changed=sorted(name for name,s in configured.items() if name in ('life','study') and s.index and name not in permitted),
                  index={k:report[k] for k in ('added','modified','moved','deleted','unchanged')})
    with store.db:
        store.set_meta('mac_refresh', dict(at=datetime.now().astimezone().isoformat(), **result))
    return result


def refresh_vps(store, home):
    from .life_intake import is_entry
    from .life_tracking import observations
    path = safe_path(Path(home)/'life.sqlite3')
    if not path.is_file():
        return dict(changed=0, omitted=0)
    db = sqlite3.connect(path.as_uri()+'?mode=ro', uri=True)
    try:
        records = [json.loads(row[0]) for row in db.execute('SELECT payload FROM records')]
    finally:
        db.close()
    bodies = []
    for record in records:
        if record['deleted']:
            continue
        text = '本人原话：\n'+record['text']
        if record['summary']:
            text += '\n\n整理（可修正）：\n'+record['summary']
        text += '\n\n所属时间：'+record['occurred_at']
        if record.get('due_at'):
            text += '\n提醒时间：'+record['due_at']+'；状态：'+record['task_status']
        if record.get('tracking'):
            text += '\n习惯／学习观测：'+json.dumps(observations(record),ensure_ascii=False)
        label = record['kind'] if is_entry(record) else '对话记忆／独立事项（不进入日记随记）'
        bodies.extend(document_bodies('astrbot',record['id'],record['day']+' · '+label,text,
                                      acquired_at=record['updated_at'],
                                      attribution='本人在AstrBot的自述；整理可修正，缺记录不等于未发生'))
    return replace_scope(store, 'life', bodies, sources={'astrbot'})

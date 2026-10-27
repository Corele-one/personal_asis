"""Local account-scoped reading library; explicit reads, no model or platform writes."""
import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

from .data_policy import exclusion_reason
from .reading import TTL, cache_metadata, render, root_for, windows
from .reading_sources import Article, SourceError, Wucai, identity
from .native_sources import HOME, xhs_configurations


def safe_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise SourceError('library_symlink_denied')
    return path


def configured_accounts(home):
    result = {}
    path = safe_path(Path(home) / 'reading-cache/wucai/manifest.sqlite3')
    if path.is_file():
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            meta = dict(db.execute('SELECT key,value FROM meta'))
        if meta.get('enabled') == '1' and meta.get('region') == 'cn':
            result[('wucai', 'cn')] = 'WUCAI 中国区'
    for account, config in xhs_configurations(home).items():
        result[('xiaohongshu', account)] = config['label']
    return result


class Library:
    def __init__(self, home, *, readonly=False, accounts=None, clock=time.time):
        self.home, self.clock = safe_path(home), clock
        self.allowed = dict(configured_accounts(home) if accounts is None else accounts)
        self.path = safe_path(self.home / 'reading-library/library.sqlite3')
        self.lock = None
        if readonly:
            self.db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=10)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            lock = safe_path(self.path.parent / '.lock')
            self.lock = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(self.lock)
                raise SourceError('library_busy') from None
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
            self.db = sqlite3.connect(self.path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1) or (readonly and version != 1):
            self.close()
            raise SourceError('library_schema_version_unsupported')
        if not readonly:
            self.db.execute('PRAGMA secure_delete=ON')
            self.db.executescript('''
              CREATE TABLE IF NOT EXISTS accounts(
                source TEXT, account TEXT, label TEXT NOT NULL, enabled INTEGER NOT NULL,
                PRIMARY KEY(source,account));
              CREATE TABLE IF NOT EXISTS blobs(
                hash TEXT PRIMARY KEY, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS observations(
                source TEXT, account TEXT, item_id TEXT, blob_hash TEXT,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, fetched_at REAL NOT NULL,
                expires_at REAL, forgotten INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(source,account,item_id),
                FOREIGN KEY(source,account) REFERENCES accounts(source,account),
                FOREIGN KEY(blob_hash) REFERENCES blobs(hash));
              CREATE TABLE IF NOT EXISTS relations(
                source TEXT, account TEXT, item_id TEXT, kind TEXT,
                first_seen REAL NOT NULL, last_seen REAL NOT NULL, occurred_at TEXT,
                PRIMARY KEY(source,account,item_id,kind),
                FOREIGN KEY(source,account,item_id) REFERENCES observations(source,account,item_id));
              CREATE TABLE IF NOT EXISTS coverage(
                source TEXT, account TEXT, stream TEXT, since TEXT, until TEXT,
                status TEXT NOT NULL, cursor TEXT NOT NULL, pages INTEGER NOT NULL,
                received INTEGER NOT NULL, checked_at REAL NOT NULL, error TEXT NOT NULL,
                PRIMARY KEY(source,account,stream,since,until));
              CREATE VIRTUAL TABLE IF NOT EXISTS library_fts USING fts5(hash UNINDEXED, text, tokenize='trigram');
              PRAGMA user_version=1;
            ''')
            with self.db:
                for (source, account), label in self.allowed.items():
                    self.db.execute('''INSERT INTO accounts VALUES(?,?,?,1)
                        ON CONFLICT(source,account) DO UPDATE SET label=excluded.label''', (source, account, label))

    def close(self):
        self.db.close()
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def require(self, source, account):
        if (source, account) not in self.allowed:
            raise SourceError('library_account_not_configured')
        row = self.db.execute('SELECT enabled FROM accounts WHERE source=? AND account=?', (source, account)).fetchone()
        if not row or row[0] != 1:
            raise SourceError('library_account_disabled')

    def put(self, source, account, article, relation=None, *, acquired=None):
        self.require(source, account)
        if relation not in (None, 'saved_article', 'favorite', 'discovery'):
            raise SourceError('library_relation_denied')
        item = identity(article.item_id)
        payload = json.dumps(asdict(article), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if len(payload.encode()) > 4 * 1024 * 1024 or exclusion_reason('', payload):
            self.forget(source, account, item)
            raise SourceError('library_credential_content_excluded')
        old = self.db.execute('SELECT * FROM observations WHERE source=? AND account=? AND item_id=?', (source, account, item)).fetchone()
        if old and old['forgotten']:
            return 'excluded'
        now = self.clock() if acquired is None else acquired
        retained = relation in ('saved_article', 'favorite') or bool(self.db.execute('''SELECT 1 FROM relations
            WHERE source=? AND account=? AND item_id=? AND kind IN ('saved_article','favorite')''', (source, account, item)).fetchone())
        fetched = now
        if old and old['blob_hash'] and (old['expires_at'] is None or old['expires_at'] > self.clock()):
            previous = self.db.execute('SELECT payload FROM blobs WHERE hash=?', (old['blob_hash'],)).fetchone()[0]
            # A list refresh never replaces a fetched body or extends its temporary lease.
            if (article.content_kind == 'metadata_only' and json.loads(previous)['content_kind'] != 'metadata_only') or now < old['fetched_at']:
                payload, fetched = previous, old['fetched_at']
        digest = hashlib.sha256(payload.encode()).hexdigest()
        content = json.loads(payload)
        index_text = '\n'.join([content['title'], content['author'], content['author_text'], content['user_note'],
                                *[v for part in content['highlights'] for v in (part['quote'], part['note'])]])
        with self.db:
            inserted = self.db.execute('INSERT OR IGNORE INTO blobs VALUES(?,?)', (digest, payload)).rowcount
            if inserted:
                self.db.execute('INSERT INTO library_fts VALUES(?,?)', (digest, index_text))
            self.db.execute('''INSERT INTO observations VALUES(?,?,?,?,?,?,?,?,0)
                ON CONFLICT(source,account,item_id) DO UPDATE SET blob_hash=excluded.blob_hash,
                first_seen=min(observations.first_seen,excluded.first_seen),
                last_seen=max(observations.last_seen,excluded.last_seen),
                fetched_at=excluded.fetched_at,expires_at=excluded.expires_at''',
                (source, account, item, digest, now, now, fetched, None if retained else fetched + TTL))
            if relation:
                self.db.execute('''INSERT INTO relations VALUES(?,?,?,?,?,?,NULL)
                    ON CONFLICT(source,account,item_id,kind) DO UPDATE SET
                    first_seen=min(relations.first_seen,excluded.first_seen),last_seen=max(relations.last_seen,excluded.last_seen)''',
                    (source, account, item, relation, now, now))
            self._prune()
        return 'stored'

    def _prune(self):
        self.db.execute('DELETE FROM library_fts WHERE hash NOT IN (SELECT blob_hash FROM observations WHERE blob_hash IS NOT NULL)')
        self.db.execute('DELETE FROM blobs WHERE hash NOT IN (SELECT blob_hash FROM observations WHERE blob_hash IS NOT NULL)')

    def read(self, source, account, item):
        self.require(source, account)
        row = self.db.execute('''SELECT o.*,b.payload FROM observations o JOIN blobs b ON b.hash=o.blob_hash
            WHERE o.source=? AND o.account=? AND o.item_id=? AND o.forgotten=0
            AND (o.expires_at IS NULL OR o.expires_at>?)''', (source, account, identity(item), self.clock())).fetchone()
        if not row:
            raise SourceError('library_item_unavailable')
        result = dict(row)
        result['content'] = json.loads(result.pop('payload'))
        result['relations'] = [dict(r) for r in self.db.execute('''SELECT kind,first_seen,last_seen,occurred_at FROM relations
            WHERE source=? AND account=? AND item_id=?''', (source, account, item))]
        result['attribution'] = 'author_text:作者原文; highlights.quote:作者原文摘录; highlights.note与user_note:用户批注; 无AI生成解释'
        return result

    def search(self, query, source=None, account=None, limit=20):
        if not isinstance(query, str) or not query.strip() or len(query) > 200 or type(limit) is not int or not 1 <= limit <= 100:
            raise SourceError('library_invalid_search')
        allowed = [(s, a) for s, a in self.allowed if (source is None or s == source) and (account is None or a == account)]
        if not allowed:
            return []
        gates, parameters = [], []
        for s, a in allowed:
            gates.append('(o.source=? AND o.account=?)')
            parameters.extend((s, a))
        if len(query.strip()) >= 3:
            match = 'o.blob_hash IN (SELECT hash FROM library_fts WHERE library_fts MATCH ?)'
            term = '"' + query.strip().replace('"', '""') + '"'
        else:
            match = 'o.blob_hash IN (SELECT hash FROM library_fts WHERE instr(lower(text),lower(?))>0)'
            term = query.strip()
        rows = self.db.execute('''SELECT o.source,o.account,o.item_id,b.payload,o.fetched_at FROM observations o
            JOIN blobs b ON b.hash=o.blob_hash JOIN accounts a ON a.source=o.source AND a.account=o.account
            WHERE o.forgotten=0 AND a.enabled=1 AND (o.expires_at IS NULL OR o.expires_at>?)
            AND (''' + ' OR '.join(gates) + ') AND ' + match + ' ORDER BY o.last_seen DESC,o.item_id LIMIT ?',
            (self.clock(), *parameters, term, limit)).fetchall()
        return [dict(source=r['source'], account=r['account'], item_id=r['item_id'], fetched_at=r['fetched_at'],
                     **{k: json.loads(r['payload'])[k] for k in ('title', 'url', 'author', 'content_kind')}) for r in rows]

    def forget(self, source, account, item):
        self.require(source, account)
        with self.db:
            self.db.execute('''INSERT INTO observations VALUES(?,?,?,NULL,?,?,?,NULL,1)
                ON CONFLICT(source,account,item_id) DO UPDATE SET blob_hash=NULL,forgotten=1''',
                (source, account, identity(item), self.clock(), self.clock(), self.clock()))
            self.db.execute('DELETE FROM relations WHERE source=? AND account=? AND item_id=?', (source, account, item))
            self._prune()
        return {'forgotten': True, 'scope': 'reading_library_only; original_platform_and_legacy_copies_unchanged'}

    def coverage(self, source, account, since, until, status, cursor, pages, received, error=''):
        self.db.execute('INSERT OR REPLACE INTO coverage VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                        (source, account, 'selections', since, until, status, cursor, pages, received, self.clock(), error))
        self.db.commit()

    def status(self):
        values = []
        for source, account in self.allowed:
            counts = self.db.execute('''SELECT count(*),sum(CASE WHEN json_extract(b.payload,'$.content_kind')!='metadata_only' THEN 1 ELSE 0 END)
                FROM observations o JOIN blobs b ON b.hash=o.blob_hash WHERE o.source=? AND o.account=? AND o.forgotten=0
                AND (o.expires_at IS NULL OR o.expires_at>?)''', (source, account, self.clock())).fetchone()
            coverage = [dict(r) for r in self.db.execute('''SELECT since,until,status,pages,received,checked_at,error
                FROM coverage WHERE source=? AND account=? ORDER BY since''', (source, account))]
            values.append(dict(source=source, account=account, items=counts[0], with_text=counts[1] or 0, coverage=coverage))
        return {'accounts': values, 'unique_payloads': self.db.execute('SELECT count(*) FROM blobs').fetchone()[0],
                'complete_account_history': False, 'background_fetch_enabled': False}


def legacy_article(raw, row):
    """Recover attributed text without inventing quote-to-comment pairings."""
    lines = raw.decode().splitlines()
    values = {'title': next((s[2:] for s in lines if s.startswith('# ')), row['item_id']),
              'author_text': [], 'user_note': [], 'highlights': [], 'media_urls': []}
    for line in lines:
        if line.startswith('[作者原文 · ') and '] ' in line:
            values['author_text'].append(line.split('] ', 1)[1])
        elif line.startswith('[用户划线 · 作者原文摘录] '):
            values['highlights'].append({'quote': line.split('] ', 1)[1], 'note': ''})
        elif line.startswith('[用户批注 · 非作者原文] '):
            values['highlights'].append({'quote': '', 'note': line.split('] ', 1)[1]})
        elif line.startswith('[用户页面笔记 · 非作者原文] '):
            values['user_note'].append(line.split('] ', 1)[1])
        elif line.startswith('[媒体链接 · 未进行OCR或音视频理解] '):
            values['media_urls'].append(line.split('] ', 1)[1])
    return Article(row['item_id'], values['title'], row['url'], row['author'], row['published_at'],
                   '\n'.join(values['author_text']), '\n'.join(values['user_note']), values['highlights'], row['content_kind'], values['media_urls'])


def import_legacy(library):
    result = {}
    for source, account in (('wucai', 'cn'), ('xiaohongshu', 'default')):
        if (source, account) not in library.allowed:
            continue
        root = safe_path(root_for(library.home, source))
        path = safe_path(root.parent / 'manifest.sqlite3')
        if not path.is_file():
            continue
        stored = 0
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute('SELECT * FROM items'):
                if row['forgotten']:
                    library.forget(source, account, row['item_id'])
                    continue
                document = safe_path(root / row['filename'])
                if document.parent != root or not document.is_file():
                    continue
                raw = document.read_bytes()
                if not cache_metadata(root, row['filename'], raw):
                    continue
                relation = ('saved_article' if source == 'wucai' else 'favorite') if row['selected'] else 'discovery'
                stored += library.put(source, account, legacy_article(raw, row), relation, acquired=row['fetched_at']) == 'stored'
        result[source] = stored
    return result


def xhs_client(home, account):
    from .credentials import CredentialStore
    from .social_reading import XiaoHongShu
    from .xhs_accounts import credential, SERVICE
    config = xhs_configurations(home).get(account)
    if not config:
        raise SourceError('library_account_not_configured')
    return XiaoHongShu(config['endpoint'], store=CredentialStore(credential(account, 'mcp'), SERVICE),
                      access_store=lambda item: CredentialStore('library:' + account + ':' + identity(item), 'local.personal-asis.reading-access'))


def sync_wucai(library, since, until, *, client=None, max_pages=10, pause=time.sleep, notify=lambda v: None, refresh=False):
    library.require('wucai', 'cn')
    if type(max_pages) is not int or not 1 <= max_pages <= 50:
        raise SourceError('library_invalid_page_budget')
    client = client or Wucai('cn')
    for start, end in windows(since, until):
        old = library.db.execute('''SELECT * FROM coverage WHERE source='wucai' AND account='cn'
            AND stream='selections' AND since=? AND until=?''', (start, end)).fetchone()
        if old and old['status'] == 'window_exhausted' and not refresh:
            notify(dict(source='wucai', since=start, until=end, status='already_checked'))
            continue
        if old and old['status'] == 'window_exhausted' and refresh:
            old = None
        cursor, pages, received = (old['cursor'], old['pages'], old['received']) if old else ('', 0, 0)
        seen = {cursor} if cursor else set()
        for count in range(max_pages):
            library.coverage('wucai', 'cn', start, end, 'reading', cursor, pages, received)
            try:
                page = client.page('selections', start, end, cursor, 20)
                for article in page.articles:
                    library.put('wucai', 'cn', article, 'saved_article')
                pages += 1
                received += len(page.articles)
                if page.more is False:
                    state, cursor = 'window_exhausted', ''
                elif page.more is None:
                    state = 'pagination_unverified'
                elif not isinstance(page.cursor, str) or not page.cursor or len(page.cursor) > 1024 or page.cursor in seen:
                    raise SourceError('library_pagination_stalled')
                else:
                    cursor = page.cursor
                    seen.add(cursor)
                    state = 'page_limit' if count == max_pages - 1 else 'reading'
                library.coverage('wucai', 'cn', start, end, state, cursor, pages, received)
                notify(dict(source='wucai', since=start, until=end, status=state, pages=pages, received=received))
                if state != 'reading':
                    break
                pause(0.5)
            except Exception as error:
                code = str(error) if isinstance(error, SourceError) else 'library_read_failed'
                library.coverage('wucai', 'cn', start, end, 'failed', cursor, pages, received, code)
                raise
        pause(0.5)


def sync_xhs(library, account, *, client=None):
    library.require('xiaohongshu', account)
    library.coverage('xiaohongshu', account, '', '', 'reading', '', 0, 0)
    try:
        client = client or xhs_client(library.home, account)
        page = client.page('selections', limit=100)
        for article in page.articles:
            library.put('xiaohongshu', account, article, 'favorite')
        library.coverage('xiaohongshu', account, '', '', 'visible_page_only', '', 1, len(page.articles))
        return {'source': 'xiaohongshu', 'account': account, 'received': len(page.articles), 'status': 'visible_page_only'}
    except Exception as error:
        code = str(error) if isinstance(error, SourceError) else 'library_read_failed'
        library.coverage('xiaohongshu', account, '', '', 'failed', '', 0, 0, code)
        raise


def fetch(library, source, account, item, *, client=None):
    library.read(source, account, item)  # Must already be a visible item for this account.
    client = client or (Wucai('cn') if source == 'wucai' else xhs_client(library.home, account))
    article = client.detail(identity(item))
    if article.item_id != item:
        raise SourceError('library_detail_identity_mismatch')
    library.put(source, account, article)
    return {'source': source, 'account': account, 'item_id': item, 'content_kind': article.content_kind}


def main():
    parser = argparse.ArgumentParser(description='本机分账号阅读资料库；不调用模型或执行平台写入')
    parser.add_argument('action', choices=['initialize', 'status', 'search', 'read', 'fetch', 'forget'])
    parser.add_argument('--home', type=Path, default=HOME)
    parser.add_argument('--source', choices=['wucai', 'xiaohongshu'])
    parser.add_argument('--account')
    parser.add_argument('--item-id')
    parser.add_argument('--query')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--max-pages', type=int, default=10)
    args = parser.parse_args()
    try:
        with Library(args.home, readonly=args.action in ('status', 'search', 'read')) as library:
            if args.action == 'initialize':
                print(json.dumps({'legacy_imported': import_legacy(library)}), flush=True)
                until = args.until or datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
                since = args.since or (datetime.fromisoformat(until).date() - timedelta(days=89)).isoformat()
                notify = lambda v: print(json.dumps(v, ensure_ascii=False), flush=True)
                failures = []
                if args.source in (None, 'wucai') and ('wucai', 'cn') in library.allowed:
                    try:
                        sync_wucai(library, since, until, max_pages=args.max_pages, notify=notify)
                    except Exception:
                        failures.append('wucai:cn')
                if args.source in (None, 'xiaohongshu'):
                    for source, account in library.allowed:
                        if source == 'xiaohongshu' and (args.account is None or account == args.account):
                            time.sleep(3)
                            try:
                                notify(sync_xhs(library, account))
                            except Exception:
                                failures.append('xiaohongshu:' + account)
                result = dict(library.status(), failed_accounts=failures)
            elif args.action == 'status':
                result = library.status()
            elif args.action == 'search':
                result = {'results': library.search(args.query, args.source, args.account, args.limit)}
            else:
                if not args.source or not args.account or not args.item_id:
                    raise SourceError('library_source_account_item_required')
                result = (fetch(library, args.source, args.account, args.item_id) if args.action == 'fetch'
                          else getattr(library, args.action)(args.source, args.account, args.item_id))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 1 if result.get('failed_accounts') else 0
    except Exception as error:
        print(json.dumps({'error': str(error) if isinstance(error, SourceError) else type(error).__name__}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

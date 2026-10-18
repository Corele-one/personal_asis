"""Local reading cache, provenance, bounded sync and existing-index integration."""

from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import time
import uuid

from .data_policy import exclusion_reason
from .reading_sources import Article, Folo, SourceError, Wucai, identity


CONNECTORS = ('wucai', 'folo', 'zhihu', 'xiaohongshu', 'wechat')
TTL = 30 * 86400


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def private_file(path, raw):
    path = Path(path)
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise SourceError('reading_symlink_storage_denied')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(raw)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def root_for(home, connector):
    if connector not in CONNECTORS:
        raise SourceError('reading_unknown_connector')
    return Path(home) / 'reading-cache' / connector / 'documents'


@contextmanager
def configuration_lock(home):
    base = Path(home) / 'reading-cache'
    if base.is_symlink():
        raise SourceError('reading_symlink_storage_denied')
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(base / '.configuration.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'a+b') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def manifest_path(root):
    return Path(root).parent / 'manifest.sqlite3'


def cache_metadata(root, relative, raw=None, clock=time.time):
    """Fail closed during every search, provider use, replay and reader request."""
    try:
        path = manifest_path(root)
        if (path.is_symlink() or Path(root).is_symlink()
                or any(p.is_symlink() for p in path.parents)
                or not path.is_file()):
            return None
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            enabled = db.execute("SELECT value FROM meta WHERE key='enabled'").fetchone()
            if enabled is None or enabled[0] != '1':
                return None
            row = db.execute('SELECT * FROM items WHERE filename=? AND forgotten=0', (relative,)).fetchone()
            if row is None or not row['selected'] and row['expires_at'] <= clock():
                return None
            if raw is not None and sha(raw) != row['cache_hash']:
                return None
            return {key: row[key] for key in ('item_id', 'url', 'author', 'published_at',
                    'fetched_at', 'content_kind', 'selected', 'classification', 'origin_key')}
    except (OSError, ValueError, sqlite3.Error):
        return None


def render(article, connector, selected, classification, acquired):
    title = ' '.join(article.title.splitlines())[:500]
    # Prefix every evidence line: excerpts retain attribution even without headings.
    lines = ['---', 'reading_cache: true', 'sensitivity: ' + ('normal' if classification == 'normal' else 'private'),
             '---', '# ' + title, '',
             '[来源说明] ' + connector + '；条目 ' + article.item_id + '；' + article.content_kind,
             '[来源说明] 收藏或订阅不代表用户认同、掌握知识或亲身经历。',
             '[原文链接] ' + (article.url or '平台未提供可验证链接'),
             '[取得时间] ' + datetime.fromtimestamp(acquired, timezone.utc).isoformat(),
             '[发表时间] ' + (article.published_at or '未知；取得时间不作为发表时间'),
             '[留存] ' + ('个人精选' if selected else '普通缓存，30天'), '']
    for line in article.author_text.splitlines():
        if line.strip():
            lines.append('[作者原文 · ' + article.content_kind + '] ' + line)
    for part in article.highlights:
        for line in part['quote'].splitlines():
            lines.append('[用户划线 · 作者原文摘录] ' + line)
        for line in part['note'].splitlines():
            lines.append('[用户批注 · 非作者原文] ' + line)
    for line in article.user_note.splitlines():
        lines.append('[用户页面笔记 · 非作者原文] ' + line)
    if article.media_urls:
        lines.append('')
    for url in article.media_urls:
        lines.append('[媒体链接 · 未进行OCR或音视频理解] ' + url)
    return ('\n'.join(lines) + '\n').encode()


class ReadingCache:
    def __init__(self, home, connector, clock=time.time):
        self.home, self.connector, self.clock = Path(home), connector, clock
        self.root = root_for(home, connector)
        self.base = self.root.parent
        if any(p.is_symlink() for p in [self.root, *self.root.parents]):
            raise SourceError('reading_symlink_storage_denied')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = manifest_path(self.root)
        if path.is_symlink():
            raise SourceError('reading_symlink_storage_denied')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        # DELETE journal allows the existing index to inspect a read-only manifest.
        self.db.execute('PRAGMA journal_mode=DELETE')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS items(
            item_id TEXT PRIMARY KEY, filename TEXT UNIQUE NOT NULL, url TEXT NOT NULL,
            author TEXT NOT NULL, published_at TEXT NOT NULL, fetched_at REAL NOT NULL,
            expires_at REAL NOT NULL, selected INTEGER NOT NULL, classification TEXT NOT NULL,
            content_kind TEXT NOT NULL, cache_hash TEXT NOT NULL, origin_key TEXT NOT NULL,
            forgotten INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS arrivals(
            item_id TEXT NOT NULL, stream TEXT NOT NULL, first_seen REAL NOT NULL,
            last_seen REAL NOT NULL, PRIMARY KEY(item_id, stream));
          CREATE TABLE IF NOT EXISTS syncs(
            query_key TEXT PRIMARY KEY, cursor TEXT NOT NULL, status TEXT NOT NULL,
            pages INTEGER NOT NULL, received INTEGER NOT NULL, updated_at REAL NOT NULL);
        ''')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    @contextmanager
    def lock(self):
        descriptor = os.open(self.base / '.lock', os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        with os.fdopen(descriptor, 'a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def enabled(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='enabled'").fetchone()
        return bool(row and row[0] == '1')

    def put(self, article, stream):
        identity(article.item_id)
        if stream not in ('subscriptions', 'selections'):
            raise SourceError('reading_invalid_stream')
        old = self.db.execute('SELECT * FROM items WHERE item_id=?', (article.item_id,)).fetchone()
        if old and old['forgotten']:
            return 'excluded'
        if any(exclusion_reason('', value) for value in [article.title, article.url, article.author,
                article.author_text, article.user_note,
                *article.media_urls,
                *[value for part in article.highlights for value in part.values()]]):
            # New credential-bearing versions immediately invalidate old content.
            if old:
                self.forget(article.item_id)
            return 'credential_excluded'
        selected = stream == 'selections' or bool(old and old['selected'])
        acquired = self.clock()
        if (old and article.content_kind == 'metadata_only'
                and old['content_kind'] != 'metadata_only'
                and cache_metadata(self.root, old['filename']) is not None):
            # Discovery must not erase a fetched body or extend its 30-day lease.
            path = self.root / old['filename']
            raw = path.read_bytes() if not path.is_symlink() else b''
            if sha(raw) != old['cache_hash']:
                raise SourceError('reading_item_not_current')
            if selected and not old['selected']:
                raw = raw.replace('[留存] 普通缓存，30天'.encode(), '[留存] 个人精选'.encode(), 1)
                private_file(path, raw)
            with self.db:
                self.db.execute('UPDATE items SET selected=?,cache_hash=? WHERE item_id=?',
                                 (int(selected), sha(raw), article.item_id))
                self.db.execute('''INSERT INTO arrivals VALUES(?,?,?,?) ON CONFLICT(item_id,stream)
                    DO UPDATE SET last_seen=excluded.last_seen''',
                    (article.item_id, stream, acquired, acquired))
            return 'stored'
        # A changed version must be classified again locally before disclosure.
        classification = 'unclassified'
        filename = sha(article.item_id.encode()) + '.md'
        raw = render(article, self.connector, selected, classification, acquired)
        private_file(self.root / filename, raw)
        # Same original URL groups channels as one source of evidence, never a vote.
        origin_key = sha(article.url.encode()) if article.url else ''
        with self.db:
            self.db.execute('''INSERT INTO items VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0)
                ON CONFLICT(item_id) DO UPDATE SET url=excluded.url,author=excluded.author,
                published_at=excluded.published_at,fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,selected=excluded.selected,
                classification=excluded.classification,content_kind=excluded.content_kind,
                cache_hash=excluded.cache_hash,origin_key=excluded.origin_key''',
                (article.item_id, filename, article.url, article.author, article.published_at,
                 acquired, acquired + TTL, int(selected), classification,
                 article.content_kind, sha(raw), origin_key))
            self.db.execute('''INSERT INTO arrivals VALUES(?,?,?,?) ON CONFLICT(item_id,stream)
                DO UPDATE SET last_seen=excluded.last_seen''',
                (article.item_id, stream, acquired, acquired))
        return 'stored'

    def forget(self, item_id):
        row = self.db.execute('SELECT filename FROM items WHERE item_id=?', (identity(item_id),)).fetchone()
        if row is None:
            raise SourceError('reading_unknown_item')
        with self.db:
            self.db.execute("UPDATE items SET forgotten=1,cache_hash='' WHERE item_id=?", (item_id,))
        (self.root / row['filename']).unlink(missing_ok=True)

    def clean(self):
        expired = self.db.execute("SELECT item_id,filename FROM items WHERE forgotten=0 AND selected=0 AND cache_hash!='' AND expires_at<=?",
                                  (self.clock(),)).fetchall()
        # Retain metadata and arrival identities, never a plaintext body copy.
        for row in expired:
            (self.root / row['filename']).unlink(missing_ok=True)
        with self.db:
            self.db.executemany("UPDATE items SET cache_hash='' WHERE item_id=?",
                                [(row['item_id'],) for row in expired])
        return len(expired)

    def classify(self, item_id, classification):
        if classification not in ('normal', 'private'):
            raise SourceError('reading_invalid_classification')
        row = self.db.execute('SELECT * FROM items WHERE item_id=? AND forgotten=0',
                               (identity(item_id),)).fetchone()
        if row is None or cache_metadata(self.root, row['filename']) is None:
            raise SourceError('reading_item_not_current')
        path = self.root / row['filename']
        if path.is_symlink():
            raise SourceError('reading_symlink_storage_denied')
        raw = path.read_bytes()
        if sha(raw) != row['cache_hash']:
            raise SourceError('reading_item_not_current')
        for previous in (b'private', b'normal'):
            raw = raw.replace(b'sensitivity: ' + previous + b'\n', b'sensitivity: ' + classification.encode() + b'\n', 1)
        private_file(path, raw)
        with self.db:
            self.db.execute('UPDATE items SET classification=?,cache_hash=? WHERE item_id=?',
                             (classification, sha(raw), item_id))


def configure(home, connector, region='cn', folo_cli=None, *, zhihu_cli=None,
              xhs_endpoint=None, xhs_binary=None, xhs_opencli=None, xhs_node=None, xhs_backend=None,
              collection_id=None, defer_auth=False):
    home = Path(home)
    with ReadingCache(home, connector) as cache, cache.lock(), configuration_lock(home):
        if connector == 'wucai' and region not in ('cn', 'eu', 'us'):
            raise SourceError('reading_invalid_region')
        existing = cache.db.execute("SELECT value FROM meta WHERE key='region'").fetchone()
        if existing and existing[0] != region:
            raise SourceError('reading_region_change_requires_separate_home')
        executables = {key: Path(value).expanduser() for key, value in
                       (('folo_cli', folo_cli), ('zhihu_cli', zhihu_cli), ('xhs_binary', xhs_binary),
                        ('xhs_opencli', xhs_opencli), ('xhs_node', xhs_node))
                       if value is not None}
        for path in executables.values():
            if not path.is_absolute() or not path.is_file():
                raise SourceError('reading_cli_not_installed')
        if xhs_endpoint is not None:
            from .social_reading import xhs_endpoint as check_endpoint
            check_endpoint(xhs_endpoint)
        if xhs_backend is not None and (connector != 'xiaohongshu' or xhs_backend not in ('mcp','opencli')):
            raise SourceError('reading_xhs_invalid_backend')
        if collection_id is not None and (connector != 'zhihu' or
                not str(collection_id).isdigit() or not 0 < int(collection_id) <= 2**63-1):
            raise SourceError('reading_invalid_zhihu_collection_id')
        with cache.db:
            cache.db.execute("INSERT OR REPLACE INTO meta VALUES('region',?)", (region,))
            cache.db.execute("INSERT OR REPLACE INTO meta VALUES('enabled','1')")
            for key, path in executables.items():
                cache.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, str(path)))
            if xhs_opencli is not None:
                if connector != 'xiaohongshu' or xhs_node is None:
                    raise SourceError('reading_opencli_node_required')
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('xhs_backend','opencli')")
            if xhs_backend is not None:
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('xhs_backend',?)", (xhs_backend,))
            if connector in ('zhihu', 'xiaohongshu') or defer_auth:
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('account_access','deferred')")
            if connector == 'xiaohongshu':
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('xhs_endpoint',?)",
                                 (xhs_endpoint or 'http://127.0.0.1:18060/mcp',))
            if collection_id is not None:
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('collection_id',?)", (str(collection_id),))
        config_path = home / 'sources.yaml'
        if config_path.exists():
            from .config import load_config, parse_config
            load_config(config_path)
            data = json.loads(config_path.read_text())
            sid = 'reading_' + connector
            previous = next((s for s in data['sources'] if s['id'] == sid), None)
            if previous and (previous['root'] != str(cache.root) or not previous.get('reading_cache')):
                raise SourceError('reading_source_id_conflict')
            if not previous:
                data['sources'].append({'id': sid, 'root': str(cache.root), 'policy': 'normal',
                    'index': True, 'remote_metadata': False, 'remote_evidence': False,
                    'formats': ['md'], 'exclude': [], 'reading_cache': True})
                parse_config(data)
                private_file(config_path, (json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
        else:
            # A separate staging home may be used before touching the live config.
            data = {'node_id': 'mac', 'sources': [{'id': 'reading_' + connector,
                'root': str(cache.root), 'policy': 'normal', 'index': True,
                'remote_metadata': False, 'remote_evidence': False, 'formats': ['md'],
                'exclude': [], 'reading_cache': True}]}
            private_file(config_path, (json.dumps(data, indent=2) + '\n').encode())
    return {'configured': connector, 'region': region if connector == 'wucai' else None,
            'account_access': 'deferred' if connector in ('zhihu','xiaohongshu') or defer_auth else 'not_requested',
            'local_only': True, 'model_granted': False, 'background_work_enabled': False}


def require_access(cache):
    if not cache.enabled():
        raise SourceError('reading_source_not_enabled')
    row = cache.db.execute("SELECT value FROM meta WHERE key='account_access'").fetchone()
    if row and row[0] == 'deferred':
        raise SourceError('reading_authorization_deferred')


def activate(home, connector):
    """Explicit later owner action; no network, verification or credential lookup."""
    with ReadingCache(home, connector) as cache, cache.lock(), cache.db:
        if not cache.enabled():
            raise SourceError('reading_configure_before_activate')
        cache.db.execute("INSERT OR REPLACE INTO meta VALUES('account_access','enabled')")
    return {'source':connector, 'account_access':'enabled', 'account_verified':False}


def client(cache):
    require_access(cache)
    if cache.connector == 'wucai':
        row = cache.db.execute("SELECT value FROM meta WHERE key='region'").fetchone()
        return Wucai(row[0])
    if cache.connector == 'zhihu':
        from .social_reading import Zhihu
        values = dict(cache.db.execute('SELECT key,value FROM meta'))
        if not values.get('zhihu_cli'):
            raise SourceError('reading_zhihu_cli_not_installed')
        return Zhihu(values['zhihu_cli'], collection_id=values.get('collection_id'))
    if cache.connector == 'xiaohongshu':
        from .social_reading import XiaoHongShu, XiaoHongShuOpenCLI
        values = dict(cache.db.execute('SELECT key,value FROM meta'))
        if values.get('xhs_backend') == 'opencli':
            return XiaoHongShuOpenCLI(values['xhs_opencli'], values['xhs_node'])
        return XiaoHongShu(values['xhs_endpoint'])
    if cache.connector == 'wechat':
        from .social_reading import WeChat
        return WeChat()
    row = cache.db.execute("SELECT value FROM meta WHERE key='folo_cli'").fetchone()
    path = row[0] if row else shutil.which('folo')
    if not path:
        raise SourceError('reading_folo_cli_not_installed')
    return Folo(path)


def windows(since, until):
    first, last = date.fromisoformat(since), date.fromisoformat(until)
    if last < first or (last - first).days > 3660:
        raise SourceError('reading_invalid_date_window')
    while first <= last:
        end = min(last, first + timedelta(days=13))
        yield first.isoformat(), end.isoformat()
        first = end + timedelta(days=1)


def sync(home, connector, stream=None, since=None, until=None, max_pages=3,
         page_size=20, resume=False, source_client=None):
    if connector == 'wechat':
        raise SourceError('reading_wechat_share_link_required')
    stream = stream or ('selections' if connector in ('wucai','zhihu') else 'subscriptions')
    if (stream not in ('subscriptions', 'selections') or type(max_pages) is not int
            or not 1 <= max_pages <= 100 or type(page_size) is not int or not 1 <= page_size <= 100):
        raise SourceError('reading_invalid_sync_bounds')
    if connector == 'wucai' and stream != 'selections':
        raise SourceError('reading_wucai_only_article_selections_supported')
    if connector != 'wucai' and (since is not None or until is not None):
        raise SourceError('reading_date_filter_not_supported_use_bounded_pages')
    today = datetime.now(timezone(timedelta(hours=8))).date()
    since, until = since or (today - timedelta(days=6)).isoformat(), until or today.isoformat()
    ranges = list(windows(since, until)) if connector == 'wucai' else [('', '')]
    report = {'connector': connector, 'stream': stream, 'pages': 0, 'received': 0,
              'stored': 0, 'excluded': 0, 'coverage': [], 'platform_mutations': 0}
    with ReadingCache(home, connector) as cache, cache.lock():
        require_access(cache)
        api = source_client or client(cache)
        cache.clean()
        for first, last in ranges:
            if report['pages'] >= max_pages:
                break
            query_key = json.dumps([stream, first, last], separators=(',', ':'))
            if connector == 'zhihu':
                row = cache.db.execute("SELECT value FROM meta WHERE key='collection_id'").fetchone()
                query_key = json.dumps([stream, row[0] if row else 'recent'], separators=(',', ':'))
            prior = cache.db.execute('SELECT * FROM syncs WHERE query_key=?', (query_key,)).fetchone()
            cursor = prior['cursor'] if resume and prior and prior['status'] != 'visible_window_exhausted' else ''
            if resume and prior and prior['status'] == 'visible_window_exhausted':
                report['coverage'].append({'since': first, 'until': last, 'status': 'previous_window_exhausted'})
                continue
            seen = {cursor}
            status = 'page_limit'
            while report['pages'] < max_pages:
                try:
                    page = api.page(stream, first, last, cursor, page_size)
                    for article in page.articles:
                        outcome = cache.put(article, stream)
                        report['stored' if outcome == 'stored' else 'excluded'] += 1
                    report['pages'] += 1
                    report['received'] += len(page.articles)
                    if page.more is False:
                        status = 'visible_window_exhausted'
                    elif page.more is None:
                        status = 'pagination_unverified'
                    elif not page.cursor or page.cursor in seen:
                        status = 'cursor_did_not_advance'
                    else:
                        cursor = page.cursor
                        seen.add(cursor)
                        status = 'page_limit'
                    with cache.db:
                        cache.db.execute('INSERT OR REPLACE INTO syncs VALUES(?,?,?,?,?,?)',
                            (query_key, cursor, status, report['pages'], report['received'], cache.clock()))
                    if status != 'page_limit':
                        break
                except SourceError as exc:
                    report['error'] = str(exc)
                    status = 'failed'
                    break
            report['coverage'].append({'since': first, 'until': last, 'status': status,
                                        'next_cursor': cursor if status == 'page_limit' else None})
            if status != 'visible_window_exhausted':
                break
        report['remaining_windows'] = len(ranges) - len(report['coverage'])
        report['complete_account_history'] = False
        report['status'] = 'failed' if 'error' in report else ('partial' if report['remaining_windows'] or
            any(c['status'] not in ('visible_window_exhausted', 'previous_window_exhausted')
                for c in report['coverage']) else 'visible_window_exhausted')
    report['index'] = refresh_index(home)
    return report


def refresh_index(home):
    from .config import load_config
    from .index import Index
    with Index(Path(home) / 'index.sqlite3', load_config(Path(home) / 'sources.yaml')) as index:
        return index.reconcile()


def fetch(home, connector, item_id, source_client=None):
    if connector == 'wechat':
        raise SourceError('reading_wechat_share_link_required')
    with ReadingCache(home, connector) as cache, cache.lock():
        require_access(cache)
        api = source_client or client(cache)
        article = api.detail(identity(item_id))
        if article.item_id != item_id:
            raise SourceError('reading_detail_identity_mismatch')
        old = cache.db.execute('SELECT 1 FROM arrivals WHERE item_id=? AND stream=?',
                               (item_id, 'selections')).fetchone()
        outcome = cache.put(article, 'selections' if old else 'subscriptions')
    return {'connector': connector, 'outcome': outcome, 'content_kind': article.content_kind,
            'index': refresh_index(home), 'platform_mutations': 0}


def status(home, connector):
    path = manifest_path(root_for(home, connector))
    if not path.exists():
        return {'connector': connector, 'configured': False}
    with ReadingCache(home, connector) as cache:
        from .credentials import CredentialStore, CredentialNotFound
        region = cache.db.execute("SELECT value FROM meta WHERE key='region'").fetchone()
        account = ('wucai:' + region[0] if connector == 'wucai' else
                   'xiaohongshu-mcp' if connector == 'xiaohongshu' else connector)
        values = dict(cache.db.execute('SELECT key,value FROM meta'))
        access = values.get('account_access', 'enabled')
        try:
            if connector == 'wechat' or access == 'deferred' or values.get('xhs_backend') == 'opencli':
                # Configuration status never verifies a deferred login or reads its credential.
                raise CredentialNotFound()
            configured = bool(CredentialStore(account, 'local.personal-asis.reading').get())
            credential = 'available' if configured else 'missing'
        except CredentialNotFound:
            credential = 'missing'
        except (OSError, ValueError):
            credential = 'unavailable'
        if connector == 'wechat':
            credential = 'not_required_for_public_share_links'
        elif access == 'deferred':
            credential = 'not_checked'
        elif values.get('xhs_backend') == 'opencli':
            credential = 'owner_browser_session_not_checked'
        return {'connector': connector, 'configured': True, 'enabled': cache.enabled(),
                'credential': credential, 'account_access': access,
                'backend': values.get('xhs_backend', 'mcp') if connector == 'xiaohongshu' else connector,
                'installed_cli': any(Path(values[key]).is_file() for key in
                                     ('folo_cli','zhihu_cli','xhs_binary','xhs_opencli') if values.get(key)),
                'items': cache.db.execute('SELECT count(*) FROM items WHERE forgotten=0').fetchone()[0],
                'selected': cache.db.execute('SELECT count(*) FROM items WHERE selected=1 AND forgotten=0').fetchone()[0],
                'syncs': [dict(row) for row in cache.db.execute('SELECT * FROM syncs')],
                'background_work_enabled': False}


def share(home, connector, url, source_client=None):
    if connector != 'wechat':
        raise SourceError('reading_share_only_wechat_supported')
    with ReadingCache(home, connector) as cache, cache.lock():
        require_access(cache)
        article = (source_client or client(cache)).share(url)
        outcome = cache.put(article, 'selections')
    return {'source': connector, 'outcome': outcome, 'content_kind': article.content_kind,
            'index': refresh_index(home)}


def discover(home, connector, query, followed_only=False, limit=20, source_client=None):
    if connector != 'xiaohongshu' or type(limit) is not int or not 1 <= limit <= 100:
        raise SourceError('reading_discovery_not_supported')
    with ReadingCache(home, connector) as cache, cache.lock():
        require_access(cache)
        page = (source_client or client(cache)).search(query, followed_only, limit)
        outcomes = [cache.put(article, 'subscriptions') for article in page.articles]
    return {'source': connector, 'received': len(outcomes), 'coverage': 'visible_results_only',
            'complete_follow_timeline': False, 'index': refresh_index(home)}


def clean(home, connector, revoke=False, item_id=None):
    with ReadingCache(home, connector) as cache, cache.lock():
        if revoke:
            with cache.db:
                cache.db.execute("INSERT OR REPLACE INTO meta VALUES('enabled','0')")
            for path in cache.root.glob('*.md'):
                path.unlink()
            with cache.db:
                cache.db.execute("UPDATE items SET cache_hash=''")
        elif item_id:
            cache.forget(identity(item_id))
        removed = cache.clean()
    report = {'expired_removed': removed, 'revoked': revoke, 'index': refresh_index(home)}
    # Reuse existing freshness propagation; retain accounting/idempotency markers.
    if (Path(home) / 'pa1.json').exists():
        from .pa1_maintenance import clean as clean_pa1
        report['derived_cleanup'] = clean_pa1(home)
    return report


def classify(home, connector, item_id, classification):
    with ReadingCache(home, connector) as cache, cache.lock():
        cache.classify(item_id, classification)
    return {'classified': True, 'model_granted': False, 'index': refresh_index(home)}


def purge_expired(home):
    removed = 0
    for connector in CONNECTORS:
        if manifest_path(root_for(home, connector)).is_file():
            with ReadingCache(home, connector) as cache, cache.lock():
                removed += cache.clean()
    return removed

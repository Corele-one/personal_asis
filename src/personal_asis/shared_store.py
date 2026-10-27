"""One logical library, two private SQLite replicas, origin-owned revisions."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sqlite3
import time

from .data_policy import exclusion_reason

NODES = ('mac', 'vps')
COLLECTIONS = ('notes', 'reading', 'life', 'annotations')
MAX_RECORD = 80_000
MAX_BATCH = 1_000_000
BODY_FIELDS = {'source', 'account', 'locator', 'title', 'text', 'url', 'part', 'parts',
               'hash', 'attribution', 'expires_at', 'acquired_at', 'coverage'}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identity(*parts):
    return hashlib.sha256(encoded(parts).encode()).hexdigest()


def safe_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('shared_symlink_denied')
    return path


def validate_body(body, collection):
    if not isinstance(body, dict) or set(body) != BODY_FIELDS:
        raise ValueError('shared_invalid_body')
    for field, limit in (('source', 40), ('account', 100), ('locator', 2000), ('title', 1500),
                         ('text', 64_000), ('url', 4000), ('hash', 64), ('attribution', 1000),
                         ('acquired_at', 80), ('coverage', 200)):
        if (not isinstance(body[field], str) or len(body[field].encode()) > limit
                or any(ord(c) < 32 and c not in '\n\r\t' for c in body[field])):
            raise ValueError('shared_invalid_body')
    if (type(body['part']) is not int or type(body['parts']) is not int
            or not 1 <= body['part'] <= body['parts'] <= 10000
            or not re.fullmatch(r'[a-f0-9]{64}', body['hash'])):
        raise ValueError('shared_invalid_parts')
    expiry = body['expires_at']
    if expiry is not None and (type(expiry) not in (int, float) or not 0 < expiry < 10**12):
        raise ValueError('shared_invalid_expiry')
    if collection == 'notes':
        relative = PurePosixPath(body['locator'])
        if (body['source'] not in ('life', 'study') or relative.is_absolute()
                or any(p in ('', '.', '..') for p in body['locator'].split('/')) or '\\' in body['locator']):
            raise ValueError('shared_invalid_note_locator')
    elif collection == 'reading' and body['source'] not in ('wucai', 'xiaohongshu'):
        raise ValueError('shared_invalid_reading_source')
    elif collection == 'life' and body['source'] != 'astrbot':
        raise ValueError('shared_invalid_life_source')
    elif collection == 'annotations':
        if body['source'] != 'annotation' or not re.fullmatch(r'(?:mac|vps)/(?:notes|reading|life)/[a-f0-9]{64}', body['locator']):
            raise ValueError('shared_invalid_annotation_source')
    value = encoded(body)
    if (len(value.encode()) > MAX_RECORD or exclusion_reason('', value)
            or re.search(r'(?<![A-Za-z0-9:.])(?:/Users/|/home/|file://|[A-Za-z]:[\\/])', value)):
        raise ValueError('shared_sensitive_content_excluded')
    if body['url']:
        from urllib.parse import urlsplit
        url = urlsplit(body['url'])
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('shared_invalid_url')
        if any(key.lower() in ('xsec_token', 'token', 'access_token', 'cookie', 'auth')
               for key, _ in __import__('urllib.parse', fromlist=['parse_qsl']).parse_qsl(url.query)):
            raise ValueError('shared_url_credential_denied')
    return body


def validate_change(value, peer):
    if (not isinstance(value, dict) or set(value) != {'origin', 'collection', 'id', 'version', 'body'}
            or value['origin'] != peer or peer not in NODES or value['collection'] not in COLLECTIONS
            or not isinstance(value['id'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['id'])
            or type(value['version']) is not int or not 1 <= value['version'] < 2**63):
        raise ValueError('shared_invalid_change')
    if ((value['collection'] in ('notes', 'reading') and peer != 'mac')
            or (value['collection'] == 'life' and peer != 'vps')):
        raise ValueError('shared_origin_authority_denied')
    if value['body'] is not None:
        validate_body(value['body'], value['collection'])
    return value


class SharedStore:
    def __init__(self, path, node):
        if node not in NODES:
            raise ValueError('shared_invalid_node')
        self.path, self.node = safe_path(path), node
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        self.db = sqlite3.connect(self.path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, 1):
            self.close()
            raise ValueError('shared_schema_version_unsupported')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS objects(
            origin TEXT, collection TEXT, id TEXT, version INTEGER NOT NULL,
            body TEXT, PRIMARY KEY(origin,collection,id));
          CREATE INDEX IF NOT EXISTS shared_revisions ON objects(origin,version);
          CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE VIRTUAL TABLE IF NOT EXISTS shared_fts USING fts5(
            title,text,tokenize='trigram');
          PRAGMA user_version=1;
        ''')
        old_node = self.get_meta('node')
        if old_node is not None and old_node != node:
            self.close()
            raise ValueError('shared_node_mismatch')
        with self.db:
            self.set_meta('node', node)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def get_meta(self, key, default=None):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)', (key, encoded(value)))

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
        except BaseException:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    def _write(self, value):
        body = None if value['body'] is None else encoded(value['body'])
        self.db.execute('''INSERT INTO objects VALUES(?,?,?,?,?)
            ON CONFLICT(origin,collection,id) DO UPDATE SET version=excluded.version,body=excluded.body''',
            (value['origin'], value['collection'], value['id'], value['version'], body))
        rowid = self.db.execute('SELECT rowid FROM objects WHERE origin=? AND collection=? AND id=?',
                               (value['origin'], value['collection'], value['id'])).fetchone()[0]
        self.db.execute('DELETE FROM shared_fts WHERE rowid=?', (rowid,))
        if body is not None:
            self.db.execute('INSERT INTO shared_fts(rowid,title,text) VALUES(?,?,?)',
                            (rowid, value['body']['title'], value['body']['text']))

    def put(self, collection, key, body, *, expected=None):
        validate_change(dict(origin=self.node, collection=collection, id=key, version=1, body=body), self.node)
        with self.transaction():
            old = self.db.execute('SELECT version,body FROM objects WHERE origin=? AND collection=? AND id=?',
                                  (self.node, collection, key)).fetchone()
            if expected is not None and expected != (old['version'] if old else 0):
                raise ValueError('shared_revision_conflict')
            if old and old['body'] == (None if body is None else encoded(body)):
                return old['version']
            if old is None and body is None:
                return 0
            revision = self.get_meta('sequence', 0) + 1
            self._write(dict(origin=self.node, collection=collection, id=key, version=revision, body=body))
            self.set_meta('sequence', revision)
            self._withdraw_annotations()
            return revision

    def _withdraw_annotations(self):
        # A source withdrawal also withdraws supplements derived from that source.
        # Only the annotation's origin writes its tombstone; the peer hides it as
        # soon as the target is gone, then receives the author's tombstone later.
        rows = self.db.execute("SELECT id,body FROM objects WHERE origin=? AND collection='annotations' AND body IS NOT NULL", (self.node,)).fetchall()
        for row in rows:
            body = json.loads(row['body'])
            target = self.db.execute('SELECT body FROM objects WHERE origin=? AND collection=? AND id=?',
                                     body['locator'].split('/')).fetchone()
            if target and (target['body'] is None or
                           (json.loads(target['body'])['expires_at'] is not None and json.loads(target['body'])['expires_at'] <= time.time())):
                revision = self.get_meta('sequence',0)+1
                self._write(dict(origin=self.node,collection='annotations',id=row['id'],version=revision,body=None))
                self.set_meta('sequence',revision)

    def export(self, after=0, *, limit=200):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('shared_invalid_cursor')
        rows = self.db.execute('''SELECT * FROM objects WHERE origin=? AND version>?
            ORDER BY version LIMIT ?''', (self.node, after, limit+1)).fetchall()
        changes, size = [], 0
        for row in rows[:limit]:
            value = dict(row);value['body'] = json.loads(row['body']) if row['body'] else None
            length = len(encoded(value).encode())
            if changes and size + length > MAX_BATCH:
                break
            changes.append(value);size += length
        return dict(changes=changes, cursor=changes[-1]['version'] if changes else after,
                    more=len(rows) > len(changes))

    def receive(self, batch, peer):
        if (peer == self.node or peer not in NODES or not isinstance(batch, dict)
                or set(batch) != {'changes', 'cursor', 'more'} or not isinstance(batch['changes'], list)
                or len(batch['changes']) > 200 or type(batch['cursor']) is not int or batch['cursor'] < 0
                or type(batch['more']) is not bool or len(encoded(batch).encode()) > MAX_BATCH + MAX_RECORD):
            raise ValueError('shared_invalid_batch')
        previous = 0
        if batch['more'] and not batch['changes']:
            raise ValueError('shared_empty_continuation')
        for change in batch['changes']:
            validate_change(change, peer)
            if change['version'] <= previous:
                raise ValueError('shared_invalid_sequence')
            previous = change['version']
        if batch['changes'] and batch['cursor'] != previous:
            raise ValueError('shared_invalid_cursor')
        with self.transaction():
            cursor = self.get_meta('received:' + peer, 0)
            if not batch['changes'] and batch['cursor'] != cursor:
                raise ValueError('shared_invalid_cursor')
            for value in batch['changes']:
                old = self.db.execute('SELECT version,body FROM objects WHERE origin=? AND collection=? AND id=?',
                    (peer, value['collection'], value['id'])).fetchone()
                body = None if value['body'] is None else encoded(value['body'])
                if old and old['version'] == value['version'] and old['body'] != body:
                    raise ValueError('shared_revision_collision')
                if old is None or old['version'] < value['version']:
                    self._write(value)
            self.set_meta('received:' + peer, max(cursor, batch['cursor']))
            self._withdraw_annotations()
        return self.get_meta('received:' + peer, 0)

    def read(self, origin, collection, key):
        row = self.db.execute('SELECT * FROM objects WHERE origin=? AND collection=? AND id=?',
                              (origin, collection, key)).fetchone()
        if not row or row['body'] is None:
            raise ValueError('shared_record_unavailable')
        result = dict(row);result['body'] = json.loads(row['body'])
        if result['body']['expires_at'] is not None and result['body']['expires_at'] <= time.time():
            raise ValueError('shared_record_expired')
        if collection == 'annotations':
            self.read(*result['body']['locator'].split('/'))
        return result

    def search(self, query, *, source='', account='', limit=12):
        if (not isinstance(query, str) or not query.strip() or len(query) > 200
                or type(limit) is not int or not 1 <= limit <= 30):
            raise ValueError('shared_invalid_search')
        term = '"' + query.strip().replace('"', '""') + '"'
        clause = 'shared_fts MATCH ?' if len(query.strip()) >= 3 else 'instr(lower(title || text),lower(?))>0'
        rows = self.db.execute('''SELECT o.* FROM shared_fts f JOIN objects o ON o.rowid=f.rowid
            WHERE ''' + clause + ''' AND o.body IS NOT NULL
            AND (?='' OR json_extract(o.body,'$.source')=?)
            AND (?='' OR json_extract(o.body,'$.account')=?)
            AND (json_extract(o.body,'$.expires_at') IS NULL OR json_extract(o.body,'$.expires_at')>?)
            AND (o.collection!='annotations' OR EXISTS(SELECT 1 FROM objects parent
                WHERE parent.origin || '/' || parent.collection || '/' || parent.id=json_extract(o.body,'$.locator')
                AND parent.body IS NOT NULL AND (json_extract(parent.body,'$.expires_at') IS NULL OR json_extract(parent.body,'$.expires_at')>?)))
            ORDER BY o.origin,o.collection,o.id LIMIT ?''',
            (term if len(query.strip()) >= 3 else query.strip(), source, source, account, account, time.time(), time.time(), limit)).fetchall()
        return [dict(origin=r['origin'], collection=r['collection'], id=r['id'], version=r['version'],
                     **{k:json.loads(r['body'])[k] for k in ('source','account','locator','title','url','part','parts')}) for r in rows]

    def status(self):
        counts = [dict(row) for row in self.db.execute('''SELECT origin,collection,count(*) AS count
            FROM objects WHERE body IS NOT NULL GROUP BY origin,collection''')]
        return dict(node=self.node, sequence=self.get_meta('sequence', 0),
                    received={peer:self.get_meta('received:'+peer, 0) for peer in NODES if peer != self.node}, counts=counts)

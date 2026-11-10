"""Thin identity/version/source/withdrawal contract around an external memory SDK.

The SDK owns memory text, vectors, search, updates and history. This database
contains only operation receipts and monotonic barriers, never another portrait.
"""
import hashlib
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import threading


class MemoryFault(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def fail(code):
    raise MemoryFault('memory_'+code)


def candidates(value, text, context='global'):
    if not isinstance(value, list) or len(value) > 4:
        fail('invalid_extraction')
    for item in value:
        if (not isinstance(item, dict) or set(item) != {'text','quote','kind','scope','topic','state'}
                or item['kind'] not in ('preference','decision') or item['state'] not in ('active','cancelled')
                or any(not isinstance(item[k], str) or not item[k].strip() or len(item[k]) > n
                    for k,n in [('text',800),('quote',2000),('scope',120),('topic',120)])
                or item['quote'] not in text
                or (item['scope'] != 'global' and item['scope'] != context and
                    (not item['scope'].startswith('project:') or item['scope'][8:] not in text))):
            fail('invalid_extraction')
    return value


class MemoryAuthority:
    def __init__(self, path, backend, extractor, *, owner='m1-synthetic-owner', fault=None):
        self.backend, self.extractor, self.owner = backend, extractor, owner
        self.fault = fault or (lambda point: None)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA secure_delete=ON')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS operations(
            key TEXT PRIMARY KEY, payload_hash TEXT, state TEXT, plan TEXT, result TEXT,provenance TEXT);
          CREATE TABLE IF NOT EXISTS versions(
            id TEXT PRIMARY KEY, version INTEGER NOT NULL, withdrawn INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS links(source TEXT, id TEXT, PRIMARY KEY(source,id));
          CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT,version INTEGER,withdrawn INTEGER);
        ''')
        Path(path).chmod(0o600)
        self.ready = False
        self.reconcile()

    def epoch(self):
        return self.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]

    def barrier(self, identifier, version, withdrawn):
        self.db.execute('INSERT OR REPLACE INTO versions VALUES(?,?,?)', (identifier,version,int(withdrawn)))
        self.db.execute('INSERT INTO events(id,version,withdrawn) VALUES(?,?,?)', (identifier,version,int(withdrawn)))

    def operation(self, key, state, *, plan=None, result=None):
        self.db.execute('UPDATE operations SET state=?,plan=coalesce(?,plan),result=coalesce(?,result) WHERE key=?',
            (state, None if plan is None else json.dumps(plan), None if result is None else json.dumps(result),key))
        self.db.commit()

    def owned(self, identifier, *, stale=False):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9-]{36}', identifier):
            fail('not_found')
        control = self.db.execute('SELECT * FROM versions WHERE id=?', (identifier,)).fetchone()
        item = self.backend.get(identifier)
        if not control or control['withdrawn'] or not item or item.get('user_id') != self.owner:
            fail('not_found')
        if not stale and item.get('metadata',{}).get('revision') != control['version']:
            fail('revision_unavailable')
        return item, control['version']

    def current_result(self, ids):
        result = []
        for identifier in ids:
            try:
                item, version = self.owned(identifier)
            except MemoryFault as error:
                if str(error) == 'memory_not_found':
                    continue
                raise
            result.append(dict(item, version=version))
        return dict(records=result, epoch=self.epoch())

    def reconcile(self):
        """Read back applied SDK writes; never rerun extraction or embedding."""
        with self.lock:
            all_items = self.backend.all(self.owner)
            if len(all_items) >= 1000:
                fail('reconciliation_limit')
            by_op = {}
            for item in all_items:
                md = item.get('metadata', {})
                by_op.setdefault(md.get('operation'), []).append(item)
            for op in self.db.execute("SELECT * FROM operations WHERE state IN ('extracting','applying','unknown')").fetchall():
                plan = json.loads(op['plan']) if op['plan'] is not None else None
                found = by_op.get(op['key'], [])
                if plan is not None and len(found) == len(plan) and all(
                        any(item.get('metadata',{}).get('index') == p['index'] and
                            item.get('metadata',{}).get('revision') == p['version'] for item in found) for p in plan):
                    for item in found:
                        revision = item['metadata']['revision']
                        old = self.db.execute('SELECT * FROM versions WHERE id=?',(item['id'],)).fetchone()
                        if not old:
                            self.barrier(item['id'],revision,False)
                        elif old['withdrawn'] or old['version'] != revision:
                            continue
                        self.db.execute('INSERT OR IGNORE INTO links VALUES(?,?)',(op['key'],item['id']))
                    self.operation(op['key'], 'done', result=[i['id'] for i in found])
                else:
                    self.operation(op['key'], 'unknown')
            for row in self.db.execute('SELECT * FROM versions WHERE withdrawn=1').fetchall():
                self.backend.erase(row['id'], self.owner)
            self.ready = True
            controlled = {r['id']:r for r in self.db.execute('SELECT * FROM versions')}
            # An older engine snapshot cannot override the latest version barriers.
            items = {i['id']:i for i in self.backend.all(self.owner)}
            for identifier, row in controlled.items():
                if not row['withdrawn'] and (identifier not in items or
                        items[identifier].get('metadata',{}).get('revision') != row['version']):
                    self.ready = False
            if any(i not in controlled for i in items):
                self.ready = False
            self.db.commit()

    def capture(self, client, args):
        allowed = {'source_id','session_id','text','scope_context','synthetic','memory_id','expected_version'}
        if set(args)-allowed or args.get('synthetic') is not True:
            fail('synthetic_input_required')
        text, source = args.get('text'), args.get('source_id')
        context = args.get('scope_context','global')
        if (not isinstance(text,str) or not 1 <= len(text) <= 4000 or
                not isinstance(source,str) or not 1 <= len(source) <= 200 or
                not isinstance(args.get('session_id',''),str) or len(args.get('session_id',''))>100 or
                not isinstance(context,str) or not context or len(context)>120):
            fail('invalid_input')
        key, fingerprint = digest([client,source]), digest(args)
        previous = self.db.execute('SELECT * FROM operations WHERE key=?',(key,)).fetchone()
        if previous:
            if self.db.execute('SELECT 1 FROM links JOIN versions USING(id) WHERE source=? AND withdrawn=1',(key,)).fetchone():
                fail('source_withdrawn')
            if previous['payload_hash'] != fingerprint:
                fail('source_conflict')
            if previous['state'] != 'done':
                fail('write_unknown_no_retry')
            return dict(self.current_result(json.loads(previous['result'] or '[]')), duplicate=True)
        identifier = args.get('memory_id')
        old = None
        version = 1
        if identifier:
            old, expected = self.owned(identifier, stale=True)
            if type(args.get('expected_version')) is not int or args['expected_version'] != expected:
                fail('version_conflict')
            version = expected+1
        elif args.get('expected_version') is not None:
            fail('target_required')
        elif not self.ready:
            fail('consistency_unavailable')
        provenance=dict(client=client,source_id=source,session_id=args.get('session_id',''),
            received_at=datetime.now(timezone.utc).isoformat(),source_text_hash=digest(text))
        self.db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',(key,fingerprint,'extracting',None,None,json.dumps(provenance)))
        self.db.commit()
        try:
            values = candidates(self.extractor(text,context),text,context)
            if identifier and (len(values)!=1 or values[0]['scope'] != old['metadata']['scope']):
                fail('correction_scope_mismatch')
            if not identifier:
                existing = self.backend.all(self.owner)
                for item in values:
                    if any(x.get('metadata',{}).get('scope')==item['scope'] and
                            x.get('metadata',{}).get('topic')==item['topic'] for x in existing):
                        fail('existing_scope_requires_explicit_correction')
            plan = [dict(index=i,version=version) for i in range(len(values))]
            self.operation(key,'applying',plan=plan)
            if identifier:
                self.barrier(identifier,version,False)
                self.db.commit()
            ids = []
            for index,item in enumerate(values):
                md = dict(item, operation=key, source_key=key, source_id=source,
                    client=client, session_id=args.get('session_id',''), revision=version,index=index,
                    received_at=provenance['received_at'],source_text_hash=provenance['source_text_hash'])
                md.pop('text')
                if identifier:
                    self.backend.update(identifier,item['text'],md)
                    saved = identifier
                else:
                    saved = self.backend.add(item['text'],self.owner,md)
                self.fault('after_sdk_write')
                if not identifier:
                    self.barrier(saved,version,False)
                self.db.execute('INSERT OR IGNORE INTO links VALUES(?,?)',(key,saved))
                self.db.commit()
                ids.append(saved)
            self.operation(key,'done',result=ids)
            self.reconcile()
            return dict(self.current_result(ids),duplicate=False)
        except Exception:
            self.operation(key,'unknown')
            self.ready = False
            fail('write_unknown_no_retry')

    def withdraw(self, args):
        if set(args)-{'memory_id','expected_version','synthetic'} or args.get('synthetic') is not True:
            fail('invalid_withdrawal')
        identifier = args.get('memory_id')
        item, version = self.owned(identifier,stale=True)
        if type(args.get('expected_version')) is not int or args['expected_version'] != version:
            fail('version_conflict')
        # This marker is committed before deleting; every source alias is blocked.
        self.barrier(identifier,version+1,True)
        self.db.commit()
        try:
            self.backend.erase(identifier,self.owner)
            self.reconcile()
        except Exception:
            fail('withdrawal_pending_cleanup')
        return dict(withdrawn=True,version=version+1,epoch=self.epoch(),
            removal_scope=['current_index','sdk_history','authority_read_caches'],
            retained_elsewhere=['original_chat','older_offline_backups_until_restored_or_pruned'])

    def dispatch(self, client, action, args):
        with self.lock:
            if not isinstance(args,dict):
                fail('invalid_arguments')
            if action=='status' and not args:
                return dict(storage_ready=True,consistency_ready=self.ready,mode='synthetic_only',
                    content_initialized=False,automatic_save_enabled=False,clients_connected=False,
                    epoch=self.epoch(),active=self.db.execute('SELECT count(*) FROM versions WHERE withdrawn=0').fetchone()[0])
            if action=='capture':
                return self.capture(client,args)
            if action=='preview' and client=='acceptance-admin':
                if set(args)!={'source_id','text','scope_context','synthetic'} or args['synthetic'] is not True:
                    fail('invalid_preview')
                if (not isinstance(args['text'],str) or not 1<=len(args['text'])<=4000 or
                        not isinstance(args['source_id'],str) or not 1<=len(args['source_id'])<=200 or
                        not isinstance(args['scope_context'],str) or not 1<=len(args['scope_context'])<=120):
                    fail('invalid_preview')
                key=digest([client,args['source_id']])
                if self.db.execute('SELECT 1 FROM operations WHERE key=?',(key,)).fetchone():
                    fail('preview_already_attempted_no_retry')
                self.db.execute('INSERT INTO operations VALUES(?,?,?,?,?,?)',(key,digest(args),'previewing',None,None,None))
                self.db.commit()
                result=candidates(self.extractor(args['text'],args['scope_context']),args['text'],args['scope_context'])
                self.operation(key,'previewed')
                return dict(candidates=result)
            if action=='withdraw':
                return self.withdraw(args)
            if not self.ready:
                fail('consistency_unavailable')
            if action=='list' and not args:
                return self.current_result([i['id'] for i in self.backend.all(self.owner)])
            if action in ('get','history') and set(args)=={'memory_id'}:
                item, version = self.owned(args['memory_id'])
                return dict(item,version=version,epoch=self.epoch()) if action=='get' else dict(
                    history=self.backend.history(item['id']),version=version,epoch=self.epoch(),
                    sources=[json.loads(r[0]) for r in self.db.execute('SELECT provenance FROM operations JOIN links ON operations.key=links.source WHERE links.id=? AND provenance IS NOT NULL',(item['id'],))])
            if action=='search' and set(args)<= {'query','scope'}:
                query=args.get('query')
                scope=args.get('scope','')
                if not isinstance(query,str) or not 1 <= len(query)<=300 or not isinstance(scope,str) or len(scope)>120:
                    fail('invalid_query')
                result=self.backend.search(query,self.owner,scope)
                return self.current_result([i['id'] for i in result])
            if action=='validate' and set(args)=={'memory_id','version'}:
                try:
                    _, version=self.owned(args['memory_id'])
                    valid=type(args['version']) is int and version==args['version']
                except MemoryFault:
                    valid=False
                return dict(valid=valid,epoch=self.epoch())
            fail('action_denied')

    def close(self):
        with self.lock:
            self.db.close()
            self.backend.close()

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from personal_asis.knowledge_service import KnowledgeService, TOOLS
from personal_asis.shared_sources import document_bodies
from personal_asis.shared_store import SharedStore, identity


class KnowledgeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.store = SharedStore(self.home/'shared.sqlite3', 'vps')
        self.addCleanup(self.store.close)
        self.now = 0
        self.calls = []
        self.service = KnowledgeService(self.home, os.getuid(), wucai=self.fake_wucai, clock=lambda:self.now)

    async def fake_wucai(self, operation, raw):
        args = json.loads(raw)
        self.calls.append((operation, args))
        if operation != 'get-article-text':
            return 'wucai_read_timeout_no_retry'
        offset = args.get('offset', 0)
        return json.dumps(dict(status='ok', note_idx='synthetic', content_hash='a'*64,
            total_chars=18000, text='合成正文', returned_range=[offset, min(offset+6000, 18000)],
            read_complete=False, next_arguments=dict(note_idx='synthetic', offset=offset+6000,
                expected_hash='a'*64) if offset+6000 < 18000 else None))

    def put(self, text='合成电路复习', locator='Study/2026-11-10.md'):
        refs = []
        for body in document_bodies('study', locator, '合成电路', text):
            key = identity('study', locator, body['part'])
            self.store.receive(dict(changes=[dict(origin='mac', collection='notes',
                id=key, version=self.store.get_meta('received:mac', 0)+1, body=body)],
                cursor=self.store.get_meta('received:mac', 0)+1, more=False), 'mac')
            refs.append(key)
        return refs

    async def call(self, name, args, uid=None):
        return await self.service.dispatch(dict(method='tools/call', params=dict(name=name, arguments=args)),
            os.getuid() if uid is None else uid)

    async def test_identity_and_all_write_actions_denied(self):
        self.put()
        before = self.store.path.read_bytes()
        for action in ('annotate', 'update_annotation', 'delete_annotation', 'refresh', 'export'):
            result = await self.call('shared_knowledge', dict(action=action))
            self.assertIn('error', result)
        self.assertEqual((await self.call('wucai_read', dict(operation='delete-article')))['error'],
            'knowledge_read_only_operation_required')
        self.assertEqual((await self.call('shared_knowledge', dict(action='status'), uid=os.getuid()+1))['error'],
            'knowledge_client_denied')
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.calls, [])

    async def test_readonly_connection_cannot_modify_or_create_replica(self):
        with SharedStore(self.store.path, 'vps', read_only=True) as reader:
            with self.assertRaises(sqlite3.OperationalError):
                reader.put('life', 'a'*64, None)
        missing = self.home/'missing.sqlite3'
        with self.assertRaises(sqlite3.OperationalError):
            SharedStore(missing, 'vps', read_only=True)
        self.assertFalse(missing.exists())

    async def test_catalog_and_exact_paginated_reads_no_refresh(self):
        self.put('甲'*12000+'乙'*100)
        before = hashlib.sha256(self.store.path.read_bytes()).hexdigest()
        page = (await self.call('shared_knowledge', dict(action='list', source='study',
            start='2026-11-10', end='2026-11-10')))['result']
        ref = page['results'][0]
        self.assertEqual(ref['read_arguments'], dict(action='read', origin=ref['origin'],
            collection=ref['collection'], record_id=ref['id'], expected_version=ref['version'],
            expected_hash=ref['content_hash']))
        result = await self.call('shared_knowledge', dict(action='read', origin=ref['origin'],
            collection=ref['collection'], record_id=ref['id'], expected_version=ref['version'],
            expected_hash=ref['content_hash']))
        count = 1
        while result['result']['next_arguments']:
            self.assertFalse(result['result']['read_complete'])
            result = await self.call('shared_knowledge', result['result']['next_arguments'])
            count += 1
        self.assertTrue(result['result']['read_complete'])
        self.assertEqual(count, 3)
        self.assertEqual(before, hashlib.sha256(self.store.path.read_bytes()).hexdigest())

    async def test_withdrawal_and_changed_version_stop_cached_reads(self):
        key = self.put('甲'*9000)[0]
        first = (await self.call('shared_knowledge', dict(action='read', origin='mac',
            collection='notes', record_id=key)))['result']
        old = self.store.read('mac', 'notes', key)
        self.store.receive(dict(changes=[dict(old, version=old['version']+1, body=None)],
            cursor=old['version']+1, more=False), 'mac')
        self.assertIn('error', await self.call('shared_knowledge', first['next_arguments']))
        page = (await self.call('shared_knowledge', dict(action='list')))['result']
        self.assertEqual(page['results'], [])

    async def test_session_expiry_and_new_session_cannot_claim_prior_reads(self):
        key = self.put('甲'*9000)[0]
        first = (await self.call('shared_knowledge', dict(action='read', origin='mac',
            collection='notes', record_id=key)))['result']
        args = first['next_arguments']
        other = dict(args);other.pop('read_session')
        self.assertIn('error', await self.call('shared_knowledge', other))
        self.now = 601
        self.assertIn('expired', (await self.call('shared_knowledge', args))['error'])

    async def test_wucai_complete_only_after_all_actual_ranges(self):
        first = (await self.call('wucai_read', dict(operation='get-article-text',
            arguments_json='{"note_idx":"synthetic"}')))['result']
        args = first['next_arguments']
        # Jumping to the final page is insufficient.
        args = dict(args, arguments_json=json.dumps(dict(note_idx='synthetic', offset=12000, expected_hash='a'*64)))
        last = (await self.call('wucai_read', args))['result']
        self.assertFalse(last['read_complete'])
        args['arguments_json'] = json.dumps(dict(note_idx='synthetic', offset=6000, expected_hash='a'*64))
        middle = (await self.call('wucai_read', args))['result']
        self.assertTrue(middle['read_complete'])
        self.assertTrue(middle['can_summarize'])
        args['arguments_json'] = '{"note_idx":"other"}'
        self.assertIn('target_changed', (await self.call('wucai_read', args))['error'])

    async def test_failure_is_not_retried_and_busy_is_explicit(self):
        result = await self.call('wucai_read', dict(operation='get-article', arguments_json='{"note_idx":"s"}'))
        self.assertEqual(result['result']['error'], 'wucai_read_timeout_no_retry')
        self.assertEqual(len(self.calls), 1)
        async with self.service.lock:
            result = await self.call('shared_knowledge', dict(action='status'))
        self.assertEqual(result['error'], 'knowledge_busy_no_retry')

    async def test_invalid_catalog_arguments_explain_repair_without_source_writes(self):
        self.put()
        before = self.store.path.read_bytes()
        for args, code in [
            (dict(action='list', source='study', limit=50), 'shared_invalid_query'),
            (dict(action='list', source='study', collection='notes'), 'knowledge_invalid_request'),
        ]:
            result = await self.call('shared_knowledge', args)
            self.assertEqual(result['error'], code)
            self.assertIn('hint', result)
            self.assertNotIn('合成电路', result['hint'])
        valid = await self.call('shared_knowledge', dict(action='list', source='study', limit=12))
        self.assertEqual(len(valid['result']['results']), 1)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.calls, [])

    async def test_no_paths_shell_sql_or_identity_arguments(self):
        for args in (dict(action='status', path='/etc/passwd'), dict(action='list', user_id='other'),
                     dict(action='read', record_id="' OR 1=1", origin='mac', collection='notes')):
            self.assertIn('error', await self.call('shared_knowledge', args))
        value = await self.service.dispatch(dict(method='tools/list'), os.getuid())
        self.assertEqual([x['name'] for x in value['tools']], ['shared_knowledge', 'wucai_read'])
        self.assertTrue(all(x['annotations']['readOnlyHint'] for x in TOOLS))


if __name__ == '__main__':
    unittest.main()

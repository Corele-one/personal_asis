import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from personal_asis.memory_authority import MemoryAuthority, MemoryFault, candidates


class FakeSDK:
    """Fault-controllable SDK double; never selectable by the running service."""
    def __init__(self):
        self.items={};self.histories={};self.writes=0

    def get(self,key):
        return copy.deepcopy(self.items.get(key))

    def all(self,owner):
        return [copy.deepcopy(i) for i in self.items.values() if i['user_id']==owner]

    def add(self,text,owner,metadata):
        key=str(uuid.uuid4());self.writes+=1
        self.items[key]=dict(id=key,memory=text,user_id=owner,metadata=copy.deepcopy(metadata))
        self.histories[key]=[dict(new_memory=text,event='ADD')]
        return key

    def update(self,key,text,metadata):
        self.writes+=1
        self.items[key].update(memory=text,metadata=copy.deepcopy(metadata))
        self.histories[key].append(dict(new_memory=text,event='UPDATE'))

    def search(self,query,owner,scope):
        return [x for x in self.all(owner) if not scope or x['metadata']['scope']==scope]

    def history(self,key):
        return copy.deepcopy(self.histories.get(key,[]))

    def erase(self,key,owner):
        self.items.pop(key,None);self.histories.pop(key,None)

    def close(self):
        pass


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'barriers.sqlite3'
        self.sdk=FakeSDK();self.extract_calls=0
        self.authority=MemoryAuthority(self.path,self.sdk,self.extract)
        self.addCleanup(lambda:self.authority.close())

    def extract(self,text,context):
        self.extract_calls+=1
        if text=='这次只写一句话。':
            return []
        return [dict(text=text,quote=text,kind='preference',scope=context,topic='language',state='active')]

    def capture(self,source='one',text='以后解释电路用中文。',client='chat',**extra):
        return self.authority.dispatch(client,'capture',dict(source_id=source,text=text,synthetic=True,**extra))

    def reopen(self,sdk=None):
        self.authority.close()
        self.authority=MemoryAuthority(self.path,sdk or self.sdk,self.extract)

    def test_shared_user_scope_and_source_origin_metadata(self):
        first=self.capture()['records'][0]
        found=self.authority.dispatch('work','search',dict(query='解释用什么语言'))['records']
        self.assertEqual(found[0]['id'],first['id'])
        self.assertEqual(found[0]['metadata']['client'],'chat')
        self.assertEqual(found[0]['metadata']['quote'],'以后解释电路用中文。')

    def test_duplicate_and_same_source_changed_body(self):
        self.capture()
        self.assertTrue(self.capture()['duplicate'])
        self.assertEqual(self.sdk.writes,1)
        self.assertEqual(self.extract_calls,1)
        with self.assertRaisesRegex(MemoryFault,'source_conflict'):
            self.capture(text='以后解释电路用英文。')
        self.assertEqual(self.extract_calls,1)

    def test_temporary_request_is_empty_without_mutating_existing_preference(self):
        saved=self.capture()['records'][0]
        ignored=self.capture('temporary','这次只写一句话。')
        self.assertEqual(ignored['records'],[])
        self.assertEqual(self.authority.dispatch('work','get',dict(memory_id=saved['id']))['memory'],saved['memory'])

    def test_two_concurrent_corrections_one_success_one_conflict(self):
        first=self.capture()['records'][0]
        def correct(value):
            try:
                return self.capture('correction-'+value,'以后解释电路用'+value+'。',
                    memory_id=first['id'],expected_version=first['version'])
            except MemoryFault as e:
                return str(e)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(correct,['英文','中文加图解']))
        self.assertEqual(sum(isinstance(r,dict) for r in results),1)
        self.assertEqual(results.count('memory_version_conflict'),1)
        self.assertEqual(self.extract_calls,2)
        self.assertEqual(self.sdk.writes,2)
        self.assertFalse(self.authority.dispatch('work','validate',dict(memory_id=first['id'],version=1))['valid'])

    def test_withdrawal_cleans_history_invalidates_cache_and_blocks_old_source(self):
        first=self.capture()['records'][0]
        self.authority.dispatch('work','withdraw',dict(memory_id=first['id'],expected_version=1,synthetic=True))
        self.assertEqual(self.sdk.history(first['id']),[])
        self.assertEqual(self.authority.dispatch('chat','search',dict(query='语言'))['records'],[])
        self.assertFalse(self.authority.dispatch('work','validate',dict(memory_id=first['id'],version=1))['valid'])
        with self.assertRaisesRegex(MemoryFault,'source_withdrawn'):
            self.capture()
        self.assertEqual(self.extract_calls,1)
        self.reopen()
        with self.assertRaisesRegex(MemoryFault,'source_withdrawn'):
            self.capture()

    def test_reconcile_write_after_sdk_commit_does_not_repeat_provider_calls(self):
        def crash(point):
            raise RuntimeError('synthetic_crash_after_sdk_commit')
        self.authority.fault=crash
        with self.assertRaisesRegex(MemoryFault,'write_unknown'):
            self.capture()
        self.assertFalse(self.authority.ready)
        self.reopen()
        self.assertTrue(self.authority.ready)
        self.assertTrue(self.capture()['duplicate'])
        self.assertEqual(self.extract_calls,1)
        self.assertEqual(self.sdk.writes,1)

    def test_unapplied_unknown_extraction_is_not_automatically_retried(self):
        def unknown(text,context):
            self.extract_calls+=1
            raise TimeoutError('synthetic_timeout')
        self.authority.extractor=unknown
        with self.assertRaisesRegex(MemoryFault,'write_unknown'):
            self.capture()
        self.reopen()
        with self.assertRaisesRegex(MemoryFault,'write_unknown'):
            self.capture()
        self.assertEqual(self.extract_calls,1)

    def test_old_backup_cannot_resurrect_withdrawn_memory(self):
        first=self.capture()['records'][0]
        backup=copy.deepcopy(self.sdk)
        self.authority.dispatch('chat','withdraw',dict(memory_id=first['id'],expected_version=1,synthetic=True))
        self.reopen(backup)
        self.assertTrue(self.authority.ready)
        self.assertIsNone(backup.get(first['id']))
        self.assertEqual(backup.history(first['id']),[])

    def test_old_backup_with_outdated_correction_refuses_reads(self):
        first=self.capture()['records'][0]
        old=copy.deepcopy(self.sdk)
        self.capture('correction','以后解释电路用英文。',memory_id=first['id'],expected_version=1)
        self.reopen(old)
        self.assertFalse(self.authority.ready)
        with self.assertRaisesRegex(MemoryFault,'consistency_unavailable'):
            self.authority.dispatch('work','search',dict(query='语言'))
        # An explicit new correction can repair an incomplete revision without
        # ever returning the stale value as current.
        self.capture('explicit-repair','以后解释电路用英文。',memory_id=first['id'],expected_version=2)
        self.assertTrue(self.authority.ready)

    def test_get_and_history_require_owned_id_and_caller_cannot_choose_user(self):
        other=self.sdk.add('other owner','not-this-owner',{})
        for action in ['get','history']:
            with self.assertRaisesRegex(MemoryFault,'not_found'):
                self.authority.dispatch('work',action,dict(memory_id=other))
        with self.assertRaisesRegex(MemoryFault,'action_denied'):
            self.authority.dispatch('work','search',dict(query='语言',user_id='not-this-owner'))
        with self.assertRaisesRegex(MemoryFault,'synthetic_input_required'):
            self.authority.dispatch('chat','capture',dict(source_id='real',text='用户资料'))

    def test_project_scopes_and_correction_scope_mismatch(self):
        a=self.capture('a',scope_context='project:甲')['records'][0]
        b=self.capture('b','以后用英文文档。',scope_context='project:乙')['records'][0]
        found=self.authority.dispatch('work','search',dict(query='文档',scope='project:甲'))['records']
        self.assertEqual([i['id'] for i in found],[a['id']])
        self.assertNotEqual(a['id'],b['id'])
        with self.assertRaisesRegex(MemoryFault,'write_unknown'):
            self.capture('bad-correction',scope_context='global',memory_id=a['id'],expected_version=1)

    def test_receipts_have_no_second_memory_text(self):
        self.capture()
        values=[tuple(r) for r in self.authority.db.execute('SELECT * FROM operations')]
        self.assertNotIn('以后解释电路用中文',json.dumps(values,ensure_ascii=False))

    def test_extraction_requires_exact_quote_and_supported_identity(self):
        value=dict(text='偏好中文',quote='原话没有这句',kind='preference',scope='global',topic='language',state='active')
        with self.assertRaisesRegex(MemoryFault,'invalid_extraction'):
            candidates([value],'真实原话')
        value.update(quote='真实原话',kind='life_fact')
        with self.assertRaisesRegex(MemoryFault,'invalid_extraction'):
            candidates([value],'真实原话')


if __name__=='__main__':
    unittest.main()

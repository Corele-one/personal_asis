from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.config import load_config, load_pa1_config
from personal_asis.data_policy import exclusion_reason
from personal_asis.index import Index
from personal_asis.model_budget import ModelBudget
from personal_asis.pa1 import authorize_current_files, configure, fixture, revoke_sources
from personal_asis.pa1_maintenance import clean
from personal_asis.retrieval import build_bundle, retrieve
from personal_asis.semantic import VectorCache


class DataPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home=fixture(self.temporary.name)
        configure(self.home)

    def reconcile(self):
        with Index(self.home/'index.sqlite3',load_pa1_config(self.home)) as index:
            return index.reconcile()

    def test_source_grant_covers_new_private_files_and_moves_without_granting_new_roots(self):
        authorize_current_files(self.home,['synthetic'],True,True)
        path=self.home/'source/new-diary.md'
        path.write_text('---\nsensitivity: private\n---\n# Synthetic diary\ncache sleep self-report\n')
        self.reconcile()
        bundle=build_bundle(self.home,'self-report')
        self.assertTrue(any(e['path_hint']=='new-diary.md' for e in bundle.evidence))
        path.rename(self.home/'source/moved-diary.md')
        self.reconcile()
        bundle=build_bundle(self.home,'self-report')
        self.assertTrue(any(e['path_hint']=='moved-diary.md' for e in bundle.evidence))
        bundle.revalidate(self.home)
        config=json.loads((self.home/'sources.yaml').read_text())
        config['sources'][0]['root']=str(self.home/'other-root')
        (self.home/'sources.yaml').write_text(json.dumps(config))
        self.assertFalse(load_pa1_config(self.home).sources[0].allows_model('mimo',True,'moved-diary.md'))

    def test_credentials_and_explicit_exclusions_never_enter_index_or_cloud_bundle(self):
        authorize_current_files(self.home,['synthetic'],True,True)
        documents={'passwords.md':'# Vault\ncache CREDENTIAL_BODY\n',
                   'inline.md':'# cache secret\napi_key = "'+'sk-'+'z'*32+'"\n',
                   'excluded.md':'---\nassistant_exclude: true\n---\ncache EXCLUDED_BODY\n',
                   'health.md':'---\nsensitivity: private\n---\n# Synthetic health\ncache sleep self-report\n'}
        for name,text in documents.items():(self.home/'source'/name).write_text(text)
        report=self.reconcile()
        self.assertEqual(report['sources'][0]['skipped_reasons'],{'assistant_excluded':1,'credential_content':1})
        with Index(self.home/'index.sqlite3',load_pa1_config(self.home)) as index:
            self.assertEqual(index.db.execute('SELECT count(*) FROM search_index WHERE text LIKE ?',('%CREDENTIAL_BODY%',)).fetchone()[0],0)
            hits=retrieve(index,'cache',provider='mimo',limit=20)['evidence']
        paths={e['path_hint'] for e in hits}
        self.assertIn('health.md',paths)
        self.assertTrue(paths.isdisjoint({'passwords.md','inline.md','excluded.md'}))

    def test_known_credential_shapes_are_excluded_but_code_placeholders_and_health_are_allowed(self):
        for text in ['password: secret12345','密码：secret12345',
                     '-----BEGIN '+ 'PRIVATE KEY-----\nsynthetic',
                     'access_token="'+'x'*28+'"']:
            with self.subTest(shape=text[:12]):
                self.assertEqual(exclusion_reason('note.md',text),'credential_content')
        for text in ['api_key="YOUR_API_KEY"','password = getpass.getpass()',
                     '我自述最近睡得晚，这不是医学诊断。','关于密码学、密钥交换和 Cookie 的学习笔记。']:
            self.assertIsNone(exclusion_reason('note.md',text))

    def test_policy_upgrade_rechecks_unchanged_files_and_purges_legacy_secret_rows(self):
        path=self.home/'source/legacy.md'
        text='# legacy secret\npassword: secret12345\n'
        path.write_text(text)
        with patch('personal_asis.index.exclusion_reason',return_value=None),patch('personal_asis.index.DATA_POLICY_VERSION','legacy'):
            self.reconcile()
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            self.assertEqual(index.search('secret12345')['results'],[])
        report=self.reconcile()
        self.assertGreater(report['deleted'],0)
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            self.assertIsNone(index.db.execute("SELECT 1 FROM documents WHERE path='legacy.md'").fetchone())
            self.assertIsNone(index.db.execute("SELECT 1 FROM search_index WHERE text LIKE '%secret12345%'").fetchone())
        self.assertEqual(path.read_text(),text)

    def test_credential_question_is_rejected_before_encoder_or_model_access(self):
        class Encoder:
            def encode(self,texts):raise AssertionError('credential_sent_to_encoder')
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            with self.assertRaisesRegex(ValueError,'query_contains_credentials'):
                retrieve(index,'api_key="'+'sk-'+'z'*32+'"',provider='mimo',encoder=Encoder())

    def test_revocation_purges_all_vector_scopes_and_response_payload_preserving_usage(self):
        authorize_current_files(self.home,['synthetic'],True,True)
        bundle=build_bundle(self.home,'cache')
        evidence=bundle.evidence[0]
        cache=VectorCache(self.home/'semantic.sqlite3')
        try:
            with cache.db:
                for scope in ('provider:mimo','provider:mimo:sources:synthetic'):
                    cache.put(scope,'model',evidence,0,'synthetic',[1.,0.])
        finally:cache.close()
        ledger=ModelBudget(self.home/'pa1.sqlite3','mac')
        try:
            ledger.reserve('revoked','fingerprint',100)
            ledger.finish('revoked','succeeded',50,{'provider':'mimo','evidence':bundle.evidence,'answer':'synthetic private answer'})
            report=revoke_sources(self.home,['synthetic'])['cleanup']
            self.assertEqual(report['vectors_removed'],2)
            self.assertEqual(report['model_results_cleared'],1)
            self.assertEqual(ledger.status()['daily_tokens'],50)
            with self.assertRaisesRegex(ValueError,'expired_or_revoked_no_retry'):
                ledger.reserve('revoked','fingerprint',100)
        finally:ledger.close()

    def test_source_delete_clears_validated_and_raw_provider_files_without_touching_originals(self):
        authorize_current_files(self.home,['synthetic'],True,True)
        evidence=build_bundle(self.home,'cache').evidence[:1]
        folder=self.home/'pa1-validation';folder.mkdir()
        validated=folder/'pa1-synthetic.json'
        validated.write_text(json.dumps({'provider':'mimo','evidence':evidence}))
        raw=folder/'pa1-synthetic-provider.json';raw.write_text(json.dumps({'content':'synthetic private answer'}))
        self.assertEqual(clean(self.home)['validation_files_removed'],0)
        (self.home/'source'/evidence[0]['path_hint']).unlink()
        self.assertEqual(clean(self.home)['validation_files_removed'],2)
        self.assertFalse(validated.exists());self.assertFalse(raw.exists())
        self.assertTrue((self.home/'source/private.md').exists())

    def test_thirty_day_expiry_keeps_request_marker_so_old_success_cannot_be_paid_again(self):
        now=[1000000.]
        path=self.home/'pa1.sqlite3'
        ledger=ModelBudget(path,'mac',clock=lambda:now[0])
        ledger.reserve('old-request','hash',100)
        ledger.finish('old-request','succeeded',40,{'answer':'synthetic response'})
        ledger.close()
        now[0]+=30*86400+1
        ledger=ModelBudget(path,'mac',clock=lambda:now[0])
        try:
            with self.assertRaisesRegex(ValueError,'expired_or_revoked_no_retry'):
                ledger.reserve('old-request','hash',100)
            self.assertEqual(ledger.db.execute('SELECT tokens,response FROM model_calls').fetchone()['tokens'],40)
            self.assertIsNone(ledger.db.execute('SELECT response FROM model_calls').fetchone()[0])
        finally:ledger.close()

    def test_private_reader_requires_own_grant_and_rechecks_revocation_and_exclusion(self):
        config=load_config(self.home/'sources.yaml')
        source=replace(config.sources[0],remote_metadata=True,private_remote_metadata=True,
                       remote_evidence=True,private_remote_evidence=True)
        config=replace(config,sources=(source,))
        with Index(self.home/'index.sqlite3',config) as index:
            index.reconcile()
            hits=[e for g in index.search('PRIVATE_BODY','pwa')['results'] for e in g['replicas']]
            self.assertEqual(len(hits),1)
            self.assertTrue(hits[0]['reader_allowed'])
            job={**hits[0],'mode':'text','cursor':0,'query':'PRIVATE_BODY'}
            self.assertEqual(index.reader(job)['status'],'ready')
        for source in [replace(source,private_remote_evidence=False),
                       replace(source,private_remote_metadata=False),
                       replace(source,remote_evidence=False)]:
            with Index(self.home/'index.sqlite3',replace(config,sources=(source,))) as index:
                self.assertEqual(index.reader(job)['status'],'denied')
        (self.home/'source/private.md').write_text('---\nassistant_exclude: true\n---\nPRIVATE_BODY\n')
        with Index(self.home/'index.sqlite3',config) as index:
            self.assertEqual(index.reader(job)['status'],'stale')

    def test_cached_answer_uses_current_private_classification_without_another_call(self):
        from personal_asis.pa1 import analyze
        from test_pa1 import FakeProvider
        for name in ['private.md','unapproved.md']:(self.home/'source'/name).unlink()
        self.reconcile()
        authorize_current_files(self.home,['synthetic'],True,True)
        configure(self.home,model='synthetic-model',enabled=True,synthetic_only=False)
        provider=FakeProvider()
        initial=analyze(self.home,'cache','classification-change',provider)
        self.assertEqual(initial['sensitivity'],'normal')
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['policy']='private'
        (self.home/'sources.yaml').write_text(json.dumps(data))
        cached=analyze(self.home,'cache','classification-change',provider)
        self.assertTrue(cached['cached'])
        self.assertEqual(cached['sensitivity'],'private')
        self.assertTrue(all(e['sensitivity']=='private' for e in cached['evidence']))
        self.assertEqual(provider.calls,1)

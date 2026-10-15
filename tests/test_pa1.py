from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError

from personal_asis.config import load_config, load_pa1_config
from personal_asis.index import Index
from personal_asis.model_budget import ModelBudget
from personal_asis.model_provider import MiMo, NoRedirect, ProviderUnknown, ProviderRejected
from personal_asis.pa1 import analyze, configure, fixture, settings, self_test
from personal_asis.retrieval import build_bundle, retrieve, context_excerpt


class MemoryKey:
    def get(self):
        return 'SYNTHETIC_TEST_KEY_ONLY'


class FakeProvider(MiMo):
    def __init__(self, behavior='good', hook=None):
        super().__init__('mac','synthetic-model',store=MemoryKey())
        self.calls=0
        self.behavior,self.hook=behavior,hook
    def complete(self,payload,secret):
        self.calls+=1
        self.payload_seen=payload
        if self.hook:
            self.hook()
        if self.behavior=='unknown':
            raise ProviderUnknown('synthetic_timeout')
        if self.behavior=='rejected':
            raise ProviderRejected('synthetic_auth_rejection')
        eid='E99' if self.behavior=='bad_citation' else 'E1'
        return {'content':json.dumps({'answer':'Synthetic cache evidence ['+eid+']',
            'citations':[eid],'uncertainty':'Synthetic evidence only'}),
            'usage':{'prompt_tokens':80,'completion_tokens':20,'total_tokens':100},
            'finish_reason':'stop','tool_calls':None}


class PA1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=fixture(self.tmp.name)
        configure(self.home,'synthetic-model',True)

    def test_model_permission_independent_from_metadata_and_reader_permissions(self):
        bundle=build_bundle(self.home,'cache')
        cloud=json.dumps(bundle.cloud_input())
        self.assertEqual(len(bundle.evidence),2)
        self.assertNotIn('PRIVATE',cloud)
        self.assertNotIn('UNAPPROVED',cloud)
        self.assertNotIn('file:',cloud)
        self.assertNotIn(str(self.home),cloud)
        self.assertFalse(load_config(self.home/'sources.yaml').sources[0].remote_metadata)
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0].update(remote_metadata=True,remote_evidence=True,model_providers=[])
        (self.home/'sources.yaml').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'no_current_provider_authorized'):
            build_bundle(self.home,'cache')

    def test_private_source_requires_separate_explicit_model_grant(self):
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['policy']='private'
        (self.home/'sources.yaml').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'private'):
            load_config(self.home/'sources.yaml')

    def test_private_model_grant_does_not_grant_remote_reading_or_new_paths(self):
        from personal_asis.pa1 import authorize_current_files
        result=authorize_current_files(self.home,['synthetic'],include_private=True)
        self.assertEqual(result['granted_current_files'],{'synthetic':4})
        source=load_pa1_config(self.home).sources[0]
        self.assertTrue(source.allows_model('mimo',True,'private.md'))
        self.assertFalse(source.shares_metadata(True,'private.md'))
        self.assertFalse(source.remote_evidence)
        self.assertFalse(source.allows_model('other',True,'private.md'))
        self.assertFalse(source.allows_model('mimo',True,'new.md'))
        self.assertEqual(len(build_bundle(self.home,'cache').evidence),3)
        data=json.loads((self.home/'pa1-policy.json').read_text())
        data['sources']['synthetic']['private_model_providers']=[]
        (self.home/'pa1-policy.json').write_text(json.dumps(data))
        self.assertNotIn('PRIVATE',json.dumps(build_bundle(self.home,'cache').cloud_input()))

    def test_private_source_grant_and_real_source_switch_are_independent(self):
        from personal_asis.pa1 import authorize_current_files
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0].update(policy='private',model_providers=[],model_paths=[])
        (self.home/'sources.yaml').write_text(json.dumps(data))
        authorize_current_files(self.home,['synthetic'],include_private=True)
        self.assertEqual(len(build_bundle(self.home,'cache').evidence),3)
        with self.assertRaisesRegex(ValueError,'synthetic_only'):
            analyze(self.home,'cache','private-grant-only',FakeProvider())
        configure(self.home,synthetic_only=False)
        provider=FakeProvider()
        self.assertEqual(analyze(self.home,'cache','private-real',provider)['citations'],['E1'])
        self.assertEqual(provider.calls,1)

    def test_source_wide_private_model_grant_includes_new_files_but_not_new_sources(self):
        from personal_asis.pa1 import authorize_current_files
        authorize_current_files(self.home,['synthetic'],include_private=True,all_source_files=True)
        source=load_pa1_config(self.home).sources[0]
        self.assertTrue(source.allows_model('mimo',True,'new-diary.md'))
        self.assertFalse(source.allows_model('other',True,'new-diary.md'))
        self.assertFalse(source.shares_metadata(True,'new-diary.md'))
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['exclude']=['excluded']
        (self.home/'sources.yaml').write_text(json.dumps(data))
        self.assertFalse(load_pa1_config(self.home).sources[0].allows_model('mimo',True,'excluded/a.md'))
        configure(self.home,synthetic_only=False)
        result=analyze(self.home,'cache','private-derived',FakeProvider())
        self.assertEqual(result['sensitivity'],'private')

    def test_separate_model_policy_preserves_pa0_config_and_rechecks_root_and_revocation(self):
        from personal_asis.config import load_pa1_config
        from personal_asis.pa1 import authorize_current_files, revoke_sources
        before=(self.home/'sources.yaml').read_bytes()
        authorize_current_files(self.home,['synthetic'],True,True)
        self.assertEqual((self.home/'sources.yaml').read_bytes(),before)
        self.assertFalse(load_config(self.home/'sources.yaml').sources[0].allows_model('mimo',True,'private.md'))
        self.assertTrue(load_pa1_config(self.home).sources[0].allows_model('mimo',True,'new.md'))
        data=json.loads(before)
        data['sources'][0]['root']=str(self.home/'other-root')
        (self.home/'sources.yaml').write_text(json.dumps(data))
        self.assertFalse(load_pa1_config(self.home).sources[0].allows_model('mimo',True,'private.md'))
        (self.home/'sources.yaml').write_bytes(before)
        bundle=build_bundle(self.home,'cache')
        revoke_sources(self.home,['synthetic'])
        with self.assertRaisesRegex(ValueError,'permission_revoked'):
            bundle.revalidate(self.home)

    def test_separate_private_grant_revoked_during_model_call_refuses_result(self):
        from personal_asis.pa1 import authorize_current_files, revoke_sources
        authorize_current_files(self.home,['synthetic'],True,True)
        configure(self.home,synthetic_only=False)
        provider=FakeProvider(hook=lambda:revoke_sources(self.home,['synthetic']))
        with self.assertRaisesRegex(ValueError,'permission_revoked'):
            analyze(self.home,'cache','sidecar-revoked',provider)

    def test_insufficient_evidence_uses_fixed_abstention_and_never_shows_uncited_model_claims(self):
        from personal_asis.model_provider import validate_answer
        bundle=build_bundle(self.home,'cache')
        response={'finish_reason':'stop','tool_calls':None,'content':json.dumps({
            'status':'insufficient_evidence','answer':'SYNTHETIC_UNCITED_PERSONAL_ASSERTION',
            'citations':[],'uncertainty':'SYNTHETIC_UNGROUNDED_EXPLANATION'})}
        result=validate_answer(response,bundle)
        self.assertEqual(result['status'],'insufficient_evidence')
        self.assertEqual(result['citations'],[])
        self.assertNotIn('SYNTHETIC_',json.dumps(result))
        bad=json.loads(response['content']);bad['status']='supported'
        response['content']=json.dumps(bad)
        with self.assertRaisesRegex(ValueError,'invalid_evidence'):
            validate_answer(response,bundle)

    def test_citation_groups_require_existing_ids_and_derive_actual_reference_index(self):
        from personal_asis.model_provider import validate_answer
        bundle=build_bundle(self.home,'cache')
        response={'finish_reason':'stop','tool_calls':None,'content':json.dumps({
            'status':'supported','answer':'Synthetic evidence [E1, E2]。',
            'citations':['E1','E2'],'uncertainty':''})}
        self.assertEqual(validate_answer(response,bundle)['citations'],['E1','E2'])
        response['content']=json.dumps({'status':'supported','answer':'Synthetic [E1]',
                                        'citations':['E1','E2'],'uncertainty':''})
        normalized=validate_answer(response,bundle)
        self.assertEqual(normalized['citations'],['E1'])
        self.assertTrue(normalized['citation_index_normalized'])
        for group in ('E1, E999','E1-E2','E1, OTHER'):
            response['content']=json.dumps({'status':'supported','answer':f'Synthetic [{group}]',
                                            'citations':['E1','E2'],'uncertainty':''})
            with self.subTest(group=group),self.assertRaisesRegex(ValueError,'invalid_evidence'):
                validate_answer(response,bundle)

    def test_model_paths_are_exact_files_not_directory_or_wildcard_grants(self):
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['model_paths']=['*.md']
        (self.home/'sources.yaml').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'no_current_provider_authorized'):
            build_bundle(self.home,'cache')

    def test_bundle_cannot_substitute_text_not_present_in_original(self):
        bundle=build_bundle(self.home,'cache')
        bundle.evidence[0]['excerpt']='fabricated private text'
        with self.assertRaisesRegex(ValueError,'context_content_mismatch'):
            bundle.revalidate(self.home)

    def test_context_uses_matching_body_instead_of_title_and_frontmatter(self):
        bundle=build_bundle(self.home,'cache')
        cache=next(e for e in bundle.evidence if e['path_hint']=='cache.md')
        self.assertIn('invalidation removes a stale entry',cache['excerpt'])
        self.assertEqual(cache['line_start'],3)
        bundle.revalidate(self.home)
        selected=context_excerpt('---\ninternal: cache\n---\n# cache\n\n'+('x'*100)+' cache body\n','cache')
        self.assertEqual(selected['line_start'],6)
        self.assertEqual(selected['column_start'],42)
        self.assertNotIn('internal:',selected['excerpt'])
        self.assertIn('cache body',selected['excerpt'])

    def test_permission_revocation_and_original_version_revalidated(self):
        bundle=build_bundle(self.home,'cache')
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['model_paths']=[]
        (self.home/'sources.yaml').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'permission_revoked'):
            bundle.revalidate(self.home)
        data['sources'][0]['model_paths']=['cache.md','coherence.md']
        (self.home/'sources.yaml').write_text(json.dumps(data))
        path=self.home/'source'/bundle.evidence[0]['path_hint']
        path.write_text(path.read_text()+'changed\n')
        with self.assertRaisesRegex(ValueError,'evidence_stale'):
            bundle.revalidate(self.home)

    def test_local_semantic_rank_finds_document_without_lexical_match(self):
        class Encoder:
            def encode(self,texts):
                return [[1.,0.] if ('coherence' in text or text=='一致性') else [0.,1.] for text in texts]
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            result=retrieve(index,'一致性',provider='mimo',encoder=Encoder())
        self.assertEqual(result['mode'],'hybrid_semantic')
        self.assertEqual(result['evidence'][0]['path_hint'],'coherence.md')
        self.assertTrue(result['semantic_enabled'])

    def test_real_sources_disabled_even_when_live_enabled(self):
        provider=FakeProvider()
        with self.assertRaisesRegex(ValueError,'synthetic_only'):
            analyze(self.home,'cache','request1',provider)
        self.assertEqual(provider.calls,0)

    def test_synthetic_label_cannot_disguise_real_text(self):
        (self.home/'source/cache.md').write_text('# Real data\n\ncache unauthorized real material\n')
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            index.reconcile()
        provider=FakeProvider()
        with self.assertRaisesRegex(ValueError,'synthetic_fixture_content'):
            self.run_analysis(provider)
        self.assertEqual(provider.calls,0)

    def run_analysis(self,provider,request='request1'):
        return analyze(self.home,'cache',request,provider,synthetic_home=self.home)

    def test_success_replay_and_usage_settlement_do_not_send_twice(self):
        provider=FakeProvider()
        result=self.run_analysis(provider)
        self.assertFalse(result['cached'])
        self.assertTrue(self.run_analysis(provider)['cached'])
        self.assertEqual(provider.calls,1)
        self.assertEqual(result['citations'],['E1'])
        with open(self.home/'pa1.sqlite3','rb') as file:
            self.assertNotIn(MemoryKey().get().encode(),file.read())
        ledger=ModelBudget(self.home/'pa1.sqlite3','mac')
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.status()['daily_tokens'],100)
        self.assertNotIn('PRIVATE',json.dumps(provider.payload_seen))
        self.assertNotIn('tools',provider.payload_seen)
        self.assertEqual(provider.payload_seen['response_format'],{'type':'json_object'})

    def test_unknown_request_retains_reservation_and_cannot_retry_after_restart(self):
        provider=FakeProvider('unknown')
        with self.assertRaisesRegex(ValueError,'unknown_reserved'):
            self.run_analysis(provider)
        with self.assertRaisesRegex(ValueError,'not_retryable_unknown'):
            self.run_analysis(FakeProvider())
        ledger=ModelBudget(self.home/'pa1.sqlite3','mac')
        self.addCleanup(ledger.close)
        self.assertGreater(ledger.status()['daily_tokens'],100)
        self.assertEqual(ledger.status()['unresolved_calls'],1)

    def test_invalid_reference_charges_actual_usage_and_refuses_replay(self):
        with self.assertRaisesRegex(ValueError,'invalid_evidence'):
            self.run_analysis(FakeProvider('bad_citation'))
        with self.assertRaisesRegex(ValueError,'not_retryable_invalid_output'):
            self.run_analysis(FakeProvider())
        ledger=ModelBudget(self.home/'pa1.sqlite3','mac')
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.status()['daily_tokens'],100)

    def test_auth_rejection_does_not_consume_tokens(self):
        with self.assertRaises(ProviderRejected):
            self.run_analysis(FakeProvider('rejected'))
        ledger=ModelBudget(self.home/'pa1.sqlite3','mac')
        self.addCleanup(ledger.close)
        self.assertEqual(ledger.status()['daily_tokens'],0)

    def test_post_call_revocation_does_not_return_unapproved_answer(self):
        def revoke():
            data=json.loads((self.home/'sources.yaml').read_text())
            data['sources'][0]['model_paths']=[]
            (self.home/'sources.yaml').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'permission_revoked'):
            self.run_analysis(FakeProvider(hook=revoke))

    def test_synthetic_self_test_never_calls_provider_without_live_flag(self):
        result=self_test(self.home)
        self.assertTrue(result['synthetic_context_verified'])
        self.assertFalse(result['live_call_made'])

    def test_configuration_rejects_secrets_and_foreign_endpoint(self):
        data=settings(self.home)
        data['api_key']='SYNTHETIC_TEST_KEY_ONLY'
        (self.home/'pa1.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'invalid_pa1_configuration'):
            settings(self.home)
        del data['api_key']
        data['endpoint']='https://example.test'
        (self.home/'pa1.json').write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError,'unsupported_model_provider'):
            settings(self.home)


class BudgetTests(unittest.TestCase):
    def test_daily_monthly_rollover_and_fingerprint_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            now=[datetime(2026,10,14,1,tzinfo=timezone.utc).timestamp()]
            ledger=ModelBudget(Path(temporary)/'budget.sqlite3','mac',daily=80,monthly=100,clock=lambda:now[0])
            self.addCleanup(ledger.close)
            ledger.reserve('one','hash1',60)
            with self.assertRaisesRegex(ValueError,'budget_exhausted'):
                ledger.reserve('two','hash2',30)
            with self.assertRaisesRegex(ValueError,'id_conflict'):
                ledger.reserve('one','different',10)
            now[0]+=86400
            self.assertEqual(ledger.status()['daily_tokens'],0)
            with self.assertRaisesRegex(ValueError,'budget_exhausted'):
                ledger.reserve('two','hash2',50)
            now[0]=datetime(2026,11,1,1,tzinfo=timezone.utc).timestamp()
            ledger.reserve('three','hash3',50)
            self.assertEqual(ledger.status()['monthly_tokens'],50)

    def test_concurrent_reservations_cannot_overbook(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'budget.sqlite3'
            ledger=ModelBudget(path,'mac',100,100)
            ledger.close()
            barrier=threading.Barrier(2)
            results=[]
            def worker(name):
                other=ModelBudget(path,'mac',100,100)
                try:
                    barrier.wait(timeout=5)
                    other.reserve(name,name,70)
                    results.append('reserved')
                except ValueError:
                    results.append('denied')
                finally:
                    other.close()
            threads=[threading.Thread(target=worker,args=(str(i),)) for i in range(2)]
            for thread in threads:thread.start()
            for thread in threads:thread.join(timeout=10)
            self.assertCountEqual(results,['reserved','denied'])


class TransportTests(unittest.TestCase):
    def test_api_contract_auth_and_no_redirect(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,_):return json.dumps({'usage':{'prompt_tokens':20,'completion_tokens':10,'total_tokens':30},
                'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}).encode()
        class Opener:
            def open(self,request,timeout):
                self.request=request
                return Response()
        opener=Opener()
        client=MiMo('mac','synthetic-model',MemoryKey(),opener)
        client.complete({'max_completion_tokens':20,'stream':False},client.credential())
        self.assertEqual(opener.request.full_url,'https://api.xiaomimimo.com/v1/chat/completions')
        self.assertEqual(opener.request.get_header('Api-key'),MemoryKey().get())
        self.assertIsNone(NoRedirect().redirect_request(None,None,302,'',{},'https://example.test'))

    def test_missing_usage_is_unknown_not_free_success(self):
        client=MiMo('mac','synthetic-model',MemoryKey())
        client.request=lambda *args:{'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
        with self.assertRaises(ProviderUnknown):
            client.complete({},client.credential())

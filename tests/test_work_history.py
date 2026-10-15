"""Synthetic delegation history with real Pi, fresh source checks, and replay."""

import contextlib
import io
import json
import shutil
import unittest

from personal_asis import pa1
from personal_asis.agent import execute, inspect, clean_sessions
from personal_asis.cli import main
from personal_asis.config import load_config
from personal_asis.domain_context import DomainContexts
from personal_asis.index import Index
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore, encoded
from personal_asis.work_history import retrieve_history, prompt_history, validate_history, MAX_BYTES
from test_agent import FakeTools
from test_domain_context import DomainFixture


class HistoryProvider(FakeTools):
    def __init__(self, marker='SYNTHETIC_PRIOR_FINDING', **kwargs):
        super().__init__(**kwargs)
        self.marker=marker
    def complete(self,payload,secret):
        reply=super().complete(payload,secret)
        if reply['finish_reason']=='stop':
            answer=json.loads(reply['content'])
            answer['answer']=self.marker+' [E1][E2].'
            reply['content']=json.dumps(answer)
        return reply


@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),
                     'optional Pi packages and Node required')
class WorkHistoryTests(DomainFixture):
    def setUp(self):
        super().setUp()
        self.approve('research')

    def approve(self,domain, sources=None, key=None):
        with DomainContexts(self.home) as contexts:
            return contexts.set(domain,'SYNTHETIC_DOMAIN_GOAL','',sources or ['synthetic'],
                                key or domain,allow_model=True)

    def run_agent(self,key,domain='research',query='cache',provider=None,**kwargs):
        return execute(self.home,query,key,['synthetic'],domain=domain,
                       provider=provider or HistoryProvider(),**kwargs)

    def history(self,domain='research',query='cache',sources=None):
        return retrieve_history(self.home,domain,query,sources or ['synthetic'])

    def test_relevance_domain_and_source_scope_filter_before_disclosure(self):
        relevant=self.run_agent('relevant')
        self.run_agent('irrelevant',query='unrelated zebras',provider=HistoryProvider(marker='ZEBRA_FINDING'))
        self.approve('life')
        self.run_agent('life',domain='life',provider=HistoryProvider(marker='OTHER_DOMAIN_CANARY'))
        records=self.history()
        self.assertEqual([r['run_id'] for r in records],[relevant['run_id']])
        wire=prompt_history('cache',records)
        self.assertIn('SYNTHETIC_PRIOR_FINDING',wire)
        for forbidden in ('OTHER_DOMAIN_CANARY','ZEBRA_FINDING','[E1]','[E2]',str(self.home),'original_uri'):
            self.assertNotIn(forbidden,wire)
        self.assertIn('不是本人确认的事实',wire)
        self.assertNotIn(relevant['run_id'],wire)

    def test_history_is_opt_in_bounded_and_final_keeps_new_evidence_citations(self):
        for key in ('a','b','c'):
            self.run_agent(key)
        self.assertEqual(len(self.history()),2)
        self.assertLessEqual(len(encoded(self.history()).encode()),MAX_BYTES)
        plain=HistoryProvider(marker='SYNTHETIC_NEW_FINDING')
        self.run_agent('plain',provider=plain)
        self.assertNotIn('SYNTHETIC_PRIOR_FINDING',json.dumps(plain.calls))
        provider=HistoryProvider(marker='SYNTHETIC_NEW_FINDING')
        result=self.run_agent('with-history',provider=provider,with_history=True)
        self.assertIn('SYNTHETIC_PRIOR_FINDING',json.dumps(provider.calls))
        self.assertEqual(len(result['result']['history_used']),2)
        self.assertEqual(result['result']['citations'],['E1','E2'])
        self.assertEqual(result['result']['searches'],1)
        self.assertEqual(result['result']['usage']['total_tokens'],180)

    def test_snapshot_is_stable_on_resume_after_new_history_and_no_paid_repeat(self):
        original=self.run_agent('original')
        first=HistoryProvider()
        partial=self.run_agent('resumable',provider=first,with_history=True,step_limit=1)
        self.assertEqual(partial['status'],'checkpointed')
        self.run_agent('newer',provider=HistoryProvider(marker='NEWER_HISTORY_CANARY'))
        second=HistoryProvider()
        result=execute(self.home,None,'resumable',resume=True,provider=second)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(second.calls),1)
        self.assertNotIn('NEWER_HISTORY_CANARY',json.dumps(second.calls))
        self.assertEqual(result['result']['history_used'][0]['run_id'],original['run_id'])
        third=HistoryProvider()
        self.assertTrue(self.run_agent('resumable',provider=third,with_history=True)['cached'])
        self.assertEqual(third.calls,[])
        with self.assertRaisesRegex(ValueError,'requires_new_explicit_domain'):
            execute(self.home,None,'resumable',resume=True,with_history=True,provider=third)

    def test_adding_history_cannot_rewrite_existing_paid_contract(self):
        self.run_agent('original')
        self.run_agent('plain',step_limit=1)
        provider=HistoryProvider()
        with self.assertRaisesRegex(ValueError,'history_conflict'):
            self.run_agent('plain',provider=provider,with_history=True)
        self.assertEqual(provider.calls,[])
        with self.assertRaisesRegex(ValueError,'requires_new_explicit_domain'):
            execute(self.home,'cache','missing-domain',['synthetic'],with_history=True,provider=provider)

    def test_source_edit_delete_and_exclusion_remove_history_without_index_refresh(self):
        self.run_agent('original')
        path=self.home/'source/cache.md'
        original=path.read_text()
        path.write_text(original+'\nSYNTHETIC_CHANGED\n')
        self.assertEqual(self.history(),[])
        path.write_text(original)
        self.assertEqual(len(self.history()),1)
        path.unlink()
        self.assertEqual(self.history(),[])
        path.write_text('---\nassistant_exclude: true\n---\n'+original)
        self.assertEqual(self.history(),[])

    def test_deleted_origin_clears_dependent_session_and_retains_paid_markers(self):
        origin=self.run_agent('origin')
        dependent=self.run_agent('dependent',with_history=True,step_limit=1)
        with WorkStore(self.home/'work.sqlite3') as work:
            work.clean(origin['delegation_id'])
        provider=HistoryProvider()
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            execute(self.home,None,'dependent',resume=True,provider=provider)
        self.assertEqual(provider.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertIsNone(work._run(dependent['run_id'])['result'])
            with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
                work.session(dependent['run_id'])
            self.assertEqual(len(work.executions(dependent['run_id'])),1)
        with contextlib.closing(pa1.budget(self.home,'mac',pa1.settings(self.home))) as ledger:
            self.assertEqual(ledger.status()['daily_tokens'],240)

    def test_transitive_dependency_revocation_and_bounded_chain(self):
        root=self.run_agent('root')
        middle=self.run_agent('middle',with_history=True)
        tip=self.run_agent('tip',with_history=True)
        eligible=self.history()
        self.assertNotIn(tip['run_id'],[r['run_id'] for r in eligible])
        with WorkStore(self.home/'work.sqlite3') as work:
            work.clean(root['delegation_id'])
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            inspect(self.home,'tip')
        self.assertEqual(clean_sessions(self.home),1)  # Remaining middle payload.
        self.assertEqual(self.history(),[])
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertEqual(len(work.executions(middle['run_id'])),3)

    def test_revocation_during_call_bills_actual_usage_without_restoring_history(self):
        origin=self.run_agent('origin')
        def revoke():
            with WorkStore(self.home/'work.sqlite3') as work:
                work.clean(origin['delegation_id'])
        provider=HistoryProvider(hook=revoke)
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            self.run_agent('inflight',provider=provider,with_history=True)
        self.assertEqual(len(provider.calls),1)
        with contextlib.closing(pa1.budget(self.home,'mac',pa1.settings(self.home))) as ledger:
            self.assertEqual(ledger.status()['daily_tokens'],240)
            self.assertEqual(ledger.status()['unresolved_calls'],0)

    def test_origin_ttl_cancellation_and_changed_result_invalidate_saved_snapshot(self):
        origin=self.run_agent('origin')
        history=self.history()
        with DomainContexts(self.home) as contexts:
            binding=contexts.for_model('research',['synthetic'])
        with WorkStore(self.home/'work.sqlite3') as work:
            work.control(origin['delegation_id'],'cancel')
        self.assertEqual(self.history(),[])
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            validate_history(self.home,history,binding,['synthetic'])
        other=self.run_agent('other')
        with WorkStore(self.home/'work.sqlite3') as work:
            work.db.execute('UPDATE agent_sessions SET at=0 WHERE run=?',(other['run_id'],))
        self.assertEqual(self.history(),[])
        newer=self.run_agent('newer')
        saved=self.history()
        with WorkStore(self.home/'work.sqlite3') as work:
            result=json.loads(work._run(newer['run_id'])['result'])
            result['answer']='CHANGED [E1][E2]'
            work.db.execute('UPDATE runs SET result=? WHERE id=?',(encoded(result),newer['run_id']))
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            validate_history(self.home,saved,binding,['synthetic'])

    def test_model_permission_revocation_and_channel_filter(self):
        self.run_agent('original')
        self.assertEqual(retrieve_history(self.home,'research','cache',['synthetic'],channel='pwa'),[])
        pa1.authorize_current_files(self.home,['synthetic'])
        pa1.revoke_sources(self.home,['synthetic'])
        with self.assertRaisesRegex(ValueError,'permission_changed'):
            self.history()

    def test_saved_channel_rechecks_historical_evidence_even_after_local_resume(self):
        config=json.loads((self.home/'sources.yaml').read_text())
        config['sources'][0].update(remote_metadata=True,remote_evidence=True)
        (self.home/'sources.yaml').write_text(json.dumps(config))
        self.run_agent('original')
        self.run_agent('pwa-history',with_history=True,channel='pwa',step_limit=1)
        # No new evidence has yet been retrieved in this checkpoint. Only the
        # previous work has evidence, so this specifically exercises its gate.
        config['sources'][0]['remote_evidence']=False
        (self.home/'sources.yaml').write_text(json.dumps(config))
        provider=HistoryProvider()
        with self.assertRaisesRegex(ValueError,'history_changed_or_revoked'):
            execute(self.home,None,'pwa-history',resume=True,provider=provider)
        self.assertEqual(provider.calls,[])

    def test_scope_cannot_narrow_into_a_broader_history_record(self):
        config=json.loads((self.home/'sources.yaml').read_text())
        other=self.home/'other-source';other.mkdir()
        (other/'cache.md').write_text('# Synthetic other\n\ncache SYNTHETIC_OTHER_SOURCE\n')
        config['sources'].append({'id':'other','root':str(other),'policy':'normal','index':True,
                                 'remote_metadata':False,'model_providers':['mimo'],'model_paths':['cache.md']})
        (self.home/'sources.yaml').write_text(json.dumps(config))
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            index.reconcile()
        self.approve('research',['synthetic','other'],'broader-domain')
        execute(self.home,'cache','broader',['synthetic','other'],domain='research',provider=HistoryProvider())
        self.assertEqual(self.history(),[])
        self.assertEqual(len(self.history(sources=['synthetic','other'])),1)

    def test_local_history_cli_is_free_and_returns_explicit_coverage(self):
        origin=self.run_agent('original')
        output=io.StringIO()
        with contextlib.redirect_stdout(output):
            code=main(['--home',str(self.home),'domain','history','--domain','research',
                       '--source','synthetic','--query','cache'])
        self.assertEqual(code,0)
        result=json.loads(output.getvalue())
        self.assertFalse(result['model_called'])
        self.assertIn('latest_200',result['coverage'])
        self.assertEqual(result['records'][0]['run_id'],origin['run_id'])

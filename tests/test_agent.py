import copy
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import pa1
from personal_asis.agent import execute, inspect, clean_sessions
from personal_asis.agent_model import ToolMiMo, runtime_reply
from personal_asis.config import load_config
from personal_asis.model_provider import ProviderUnknown
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore


class FakeTools(ToolMiMo):
    def __init__(self, hook=None, behavior='good'):
        super().__init__('mac','synthetic-model')
        self.calls=[]
        self.hook=hook
        self.behavior=behavior
    def credential(self):
        return 'SYNTHETIC_TEST_CREDENTIAL'
    def complete(self,payload,secret):
        self.calls.append(copy.deepcopy(payload))
        if self.hook:
            self.hook()
        if self.behavior=='unknown':
            raise ProviderUnknown('synthetic_timeout')
        if self.behavior=='length':
            return {'content':'partial','tool_calls':None,'finish_reason':'length',
                    'usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        if not any(m['role']=='tool' for m in payload['messages']):
            return {'content':None,'tool_calls':[{'id':'call-1','type':'function','function':{
                'name':'search_notes','arguments':json.dumps({'query':'cache'})}}],
                'finish_reason':'tool_calls','usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        return {'content':json.dumps({'status':'supported','answer':'Synthetic cache evidence [E1][E2].',
                 'citations':['E1','E2'],'uncertainty':'Synthetic partial retrieval only.'}),
                'tool_calls':None,'finish_reason':'stop',
                'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}


@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(), 'optional Pi packages and Node required')
class AgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        self.key='synthetic-agent-test'

    def run_agent(self,provider=None,**kwargs):
        return execute(self.home,'cache',self.key,['synthetic'],provider=provider or FakeTools(),**kwargs)

    def ledger(self):
        ledger=pa1.budget(self.home,'mac',pa1.settings(self.home))
        self.addCleanup(ledger.close)
        return ledger

    def test_real_pi_host_uses_pa1_filter_shared_budget_and_validated_final(self):
        provider=FakeTools()
        result=self.run_agent(provider)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['usage']['total_tokens'],180)
        self.assertEqual(self.ledger().status()['daily_tokens'],180)
        wire=json.dumps(provider.calls)
        for marker in ('PRIVATE_','UNAPPROVED_','file:',str(self.home)):
            self.assertNotIn(marker,wire)
        self.assertEqual(result['result']['citations'],['E1','E2'])
        self.assertEqual(result['result']['coverage'],'current_authorized_matches_only')
        self.assertEqual([t['function']['name'] for t in provider.calls[0]['tools']],['search_notes'])
        self.assertEqual(provider.calls[0]['thinking'],{'type':'disabled'})
        self.assertEqual(inspect(self.home,self.key)['status'],'completed')

    def test_restart_after_model_commit_replays_without_paid_or_tool_repeat(self):
        first=FakeTools()
        partial=self.run_agent(first,step_limit=1)
        self.assertEqual(partial['status'],'checkpointed')
        self.assertEqual(len(first.calls),1)
        second=FakeTools()
        final=execute(self.home,None,self.key,resume=True,provider=second)
        self.assertEqual(final['status'],'completed')
        self.assertEqual(len(second.calls),1)
        self.assertTrue(any(m['role']=='tool' for m in second.calls[0]['messages']))
        third=FakeTools()
        cached=self.run_agent(third)
        self.assertTrue(cached['cached'])
        self.assertEqual(third.calls,[])
        self.assertEqual(self.ledger().status()['daily_tokens'],180)
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertEqual(len(work.executions(final['run_id'])),3)

    def test_pause_after_search_resume_and_scope_conflict(self):
        partial=self.run_agent(step_limit=2)
        with WorkStore(self.home/'work.sqlite3') as work:
            work.control(partial['delegation_id'],'pause')
        provider=FakeTools()
        waiting=self.run_agent(provider)
        self.assertEqual(waiting['status'],'paused')
        self.assertEqual(provider.calls,[])
        final=execute(self.home,None,self.key,resume=True,provider=provider)
        self.assertEqual(final['status'],'completed')
        self.assertEqual(len(provider.calls),1)
        with self.assertRaisesRegex(ValueError,'conflict'):
            execute(self.home,'changed question',self.key,['synthetic'],provider=provider)

    def test_unknown_call_blocks_recovery_and_never_rebooks(self):
        first=FakeTools(behavior='unknown')
        with self.assertRaisesRegex(ValueError,'unknown_no_retry'):
            self.run_agent(first)
        second=FakeTools()
        state=execute(self.home,None,self.key,resume=True,provider=second)
        self.assertEqual(state['unresolved_executions'],1)
        self.assertEqual(second.calls,[])
        self.assertEqual(self.ledger().status()['unresolved_calls'],1)

    def test_crash_after_billing_before_checkpoint_cannot_repeat_paid_call(self):
        provider=FakeTools()
        with patch.object(WorkStore,'commit_action',side_effect=RuntimeError('synthetic crash')):
            with self.assertRaisesRegex(RuntimeError,'synthetic crash'):
                self.run_agent(provider)
        self.assertEqual(self.ledger().status()['daily_tokens'],60)
        self.assertEqual(self.ledger().status()['unresolved_calls'],0)
        next_provider=FakeTools()
        state=execute(self.home,None,self.key,resume=True,provider=next_provider)
        self.assertEqual(state['unresolved_executions'],1)
        self.assertEqual(next_provider.calls,[])

    def test_revoke_after_search_purges_replay_and_results_before_new_model(self):
        pa1.authorize_current_files(self.home,['synthetic'])
        partial=self.run_agent(step_limit=2)
        result=pa1.revoke_sources(self.home,['synthetic'])
        self.assertEqual(result['cleanup']['agent_sessions_cleared'],1)
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
            execute(self.home,None,self.key,resume=True,provider=provider)
        self.assertEqual(provider.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            row=work.db.execute('SELECT payload FROM agent_sessions').fetchone()
            self.assertIsNone(row[0])
            self.assertIsNone(work.view(partial['delegation_id'])['runs'][0]['checkpoint'])

    def test_revoke_during_known_paid_response_clears_body_but_keeps_exact_usage(self):
        pa1.authorize_current_files(self.home,['synthetic'])
        self.run_agent(step_limit=2)
        provider=FakeTools(hook=lambda:pa1.revoke_sources(self.home,['synthetic']))
        with self.assertRaisesRegex(ValueError,'revoked_or_changed'):
            execute(self.home,None,self.key,resume=True,provider=provider)
        self.assertEqual(self.ledger().status()['daily_tokens'],180)
        self.assertEqual(self.ledger().status()['unresolved_calls'],0)
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertIsNone(work.db.execute('SELECT payload FROM agent_sessions').fetchone()[0])

    def test_known_abstention_without_search_is_not_published_or_paid_again(self):
        class Abstaining(FakeTools):
            def complete(self,payload,secret):
                self.calls.append(payload)
                return {'content':json.dumps({'status':'insufficient_evidence','answer':'uncited',
                    'citations':[],'uncertainty':'unknown'}),'tool_calls':None,'finish_reason':'stop',
                    'usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        provider=Abstaining()
        with self.assertRaisesRegex(ValueError,'requires_search'):
            self.run_agent(provider)
        with self.assertRaisesRegex(ValueError,'requires_search'):
            self.run_agent(provider)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(self.ledger().status()['daily_tokens'],60)

    def test_source_edit_after_search_refuses_stale_replay(self):
        self.run_agent(step_limit=2)
        (self.home/'source/cache.md').write_text('# Synthetic changed\n\nchanged cache evidence\n')
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'stale'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(self.ledger().status()['daily_tokens'],60)

    def test_pause_during_paid_call_discards_output_but_settles_known_usage(self):
        def pause():
            with WorkStore(self.home/'work.sqlite3') as work:
                did=work.list()[0]['id']
                work.control(did,'pause')
        provider=FakeTools(hook=pause)
        with self.assertRaisesRegex(ValueError,'stale'):
            self.run_agent(provider)
        self.assertEqual(self.ledger().status()['daily_tokens'],60)
        self.assertEqual(self.ledger().status()['unresolved_calls'],0)
        result=execute(self.home,None,self.key,resume=True,provider=FakeTools())
        self.assertEqual(result['unresolved_executions'],1)

    def test_invalid_paid_output_accounted_and_not_retried(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):
            self.run_agent(FakeTools(behavior='length'))
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'not_retryable_rejected'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(self.ledger().status()['daily_tokens'],60)

    def test_budget_failure_never_calls_provider_and_retains_local_search(self):
        ledger=self.ledger()
        ledger.reserve('other-role','synthetic',100000)
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'budget_exhausted'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(len(pa1.build_bundle(self.home,'cache').evidence),2)

    def test_cooldown_preflight_preserves_unattempted_request_for_explicit_resume(self):
        ledger=self.ledger()
        ledger.reserve('another-request','fp',100)
        ledger.finish('another-request','unknown',diagnostic={
            'http_status':429,'category':'rate_signal','retry_after_seconds':600})
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'provider_cooldown'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            rid=work.db.execute('SELECT id FROM runs').fetchone()[0]
            self.assertEqual(work.executions(rid),[])
        ledger.db.execute('UPDATE provider_cooldowns SET until_at=0')
        result=execute(self.home,None,self.key,resume=True,provider=provider)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(len(provider.calls),2)
        self.assertEqual(ledger.status()['daily_tokens'],280)

    def test_search_cap_finalizes_and_replays_final_only_protocol_without_payment(self):
        class RepeatedSearch(FakeTools):
            def complete(self,payload,secret):
                if 'tools' not in payload:
                    return super().complete(payload,secret)
                self.calls.append(copy.deepcopy(payload))
                return {'content':None,'tool_calls':[{'id':f'call-{len(self.calls)}','type':'function',
                    'function':{'name':'search_notes','arguments':'{"query":"cache"}'}}],
                    'finish_reason':'tool_calls','usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        provider=RepeatedSearch()
        partial=self.run_agent(provider,step_limit=7)
        self.assertEqual(partial['status'],'checkpointed')
        self.assertEqual(len(provider.calls),4)
        self.assertNotIn('tools',provider.calls[-1])
        resumed=RepeatedSearch()
        result=execute(self.home,None,self.key,resume=True,provider=resumed)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['result']['searches'],3)
        self.assertEqual(resumed.calls,[])
        self.assertEqual(self.ledger().status()['daily_tokens'],300)

    def test_old_saved_fourth_search_gets_refusal_then_final_without_repeating_reads(self):
        class RepeatedSearch(FakeTools):
            def complete(self,payload,secret):
                if 'tools' not in payload:
                    return super().complete(payload,secret)
                self.calls.append(copy.deepcopy(payload))
                return {'content':None,'tool_calls':[{'id':f'call-{len(self.calls)}','type':'function',
                    'function':{'name':'search_notes','arguments':'{"query":"cache"}'}}],
                    'finish_reason':'tool_calls','usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        # Reproduce a checkpoint written by the previous tool-limit behavior.
        with patch('personal_asis.agent.search_count',return_value=0):
            partial=self.run_agent(RepeatedSearch(),step_limit=7)
        self.assertEqual(partial['status'],'checkpointed')
        provider=RepeatedSearch()
        with patch('personal_asis.agent.build_bundle') as reads:
            result=execute(self.home,None,self.key,resume=True,provider=provider)
        reads.assert_not_called()
        self.assertEqual(result['result']['searches'],3)
        self.assertEqual(len(provider.calls),1)
        self.assertIn('search_limit_reached',json.dumps(provider.calls[0]))
        self.assertNotIn('tools',provider.calls[0])
        self.assertEqual(self.ledger().status()['daily_tokens'],360)

    def test_final_only_model_cannot_reopen_tool_access(self):
        class NeverStops(FakeTools):
            def complete(self,payload,secret):
                self.calls.append(payload)
                return {'content':None,'tool_calls':[{'id':f'call-{len(self.calls)}','type':'function',
                    'function':{'name':'search_notes','arguments':'{"query":"cache"}'}}],
                    'finish_reason':'tool_calls','usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}
        provider=NeverStops()
        with self.assertRaisesRegex(ValueError,'tool_requested_after_search_limit'):
            self.run_agent(provider)
        self.assertEqual(len(provider.calls),4)
        self.assertNotIn('tools',provider.calls[-1])
        self.assertEqual(self.ledger().status()['daily_tokens'],240)

    def test_completed_result_purged_on_revoke_or_expiry_never_called_again(self):
        result=self.run_agent()
        with WorkStore(self.home/'work.sqlite3') as work:
            work.db.execute('UPDATE agent_sessions SET at=at-?',(31*86400,))
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertIsNone(work.view(result['delegation_id'])['runs'][0]['result'])
            self.assertEqual(len(work.executions(result['run_id'])),3)

    def test_replayed_payload_tampering_rejected_before_new_paid_call(self):
        self.run_agent(step_limit=2)
        with WorkStore(self.home/'work.sqlite3') as work:
            row=work.db.execute('SELECT run,payload FROM agent_sessions').fetchone()
            state=json.loads(row['payload'])
            state['evidence'][0]['excerpt']='FABRICATED_SYNTHETIC_BODY'
            work.db.execute('UPDATE agent_sessions SET payload=? WHERE run=?',(json.dumps(state),row['run']))
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'content_mismatch'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])

    def test_disabled_model_clears_session_and_never_calls_provider(self):
        self.run_agent(step_limit=1)
        pa1.configure(self.home,enabled=False)
        self.assertEqual(clean_sessions(self.home),1)
        provider=FakeTools()
        with self.assertRaisesRegex(ValueError,'expired_or_cleared'):
            self.run_agent(provider)
        self.assertEqual(provider.calls,[])


class AgentProtocolTests(unittest.TestCase):
    def test_invalid_tool_shapes_ids_duplicates_and_length_are_rejected(self):
        base={'content':None,'tool_calls':[{'id':'x','type':'function','function':{
            'name':'search_notes','arguments':'{"query":"cache"}'}}],'finish_reason':'tool_calls'}
        for change in ('bad_json','duplicate_id','bad_id','not_object','length'):
            value=copy.deepcopy(base)
            if change=='bad_json':value['tool_calls'][0]['function']['arguments']='{'
            if change=='duplicate_id':value['tool_calls']*=2
            if change=='bad_id':value['tool_calls'][0]['id']='bad/path'
            if change=='not_object':value['tool_calls'][0]['function']['arguments']='[]'
            if change=='length':value['finish_reason']='length'
            with self.subTest(change=change),self.assertRaises(ValueError):
                runtime_reply(value)


if __name__=='__main__':
    unittest.main()

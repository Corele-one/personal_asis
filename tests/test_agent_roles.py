"""Real Pi with synthetic, billed role responses and durable host state."""
import copy
import json
import shutil
import tempfile
import unittest

from personal_asis import pa1
from personal_asis.agent import execute, inspect
from personal_asis.agent_model import ToolMiMo
from personal_asis.agent_roles import plan
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore
from personal_asis.model_provider import ProviderUnknown


class RolesProvider(ToolMiMo):
    def __init__(self,hook=None,unknown=False,search_again=False):
        super().__init__('mac','synthetic-model')
        self.calls=[];self.hook=hook;self.unknown=unknown;self.search_again=search_again
    def credential(self):return 'SYNTHETIC_CREDENTIAL'
    def complete(self,payload,secret):
        self.calls.append(copy.deepcopy(payload))
        if self.hook:self.hook()
        if self.unknown:raise ProviderUnknown('synthetic_timeout')
        if self.search_again and 'tools' in payload and not any(m['role']=='tool' for m in payload['messages']):
            return {'content':None,'tool_calls':[{'id':'more','type':'function','function':{
                'name':'search_notes','arguments':'{"query":"coherence"}'}}],
                'finish_reason':'tool_calls','usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}
        marker='SPECIALIST_ONLY_ANALYSIS' if 'tools' not in payload else 'SUPERVISOR_SYNTHESIS'
        return {'content':json.dumps({'status':'supported','answer':marker+' [E1][E2]',
            'citations':['E1','E2'],'uncertainty':'Synthetic evidence only'}),
            'tool_calls':None,'finish_reason':'stop',
            'usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}


class RoutingTests(unittest.TestCase):
    def test_explicit_auto_and_multi_domain_routes_are_bounded(self):
        self.assertEqual(plan('auto','申请与职业，睡眠和学习')['roles'],['career','life','research'])
        self.assertEqual(plan('auto','cache')['roles'],['research'])
        self.assertEqual(plan('life','cache')['roles'],['life'])
        self.assertEqual(len(plan('team','cache')['roles']),3)
        with self.assertRaisesRegex(ValueError,'unknown_role'):
            plan('shell','cache')


@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),
                     'optional Pi packages and Node required')
class RoleExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
    def run_agent(self,key='role-work',provider=None,**kw):
        return execute(self.home,'cache',key,['synthetic'],provider=provider or RolesProvider(),**kw)
    def ledger(self):
        ledger=pa1.budget(self.home,'mac',pa1.settings(self.home));self.addCleanup(ledger.close)
        return ledger

    def test_four_roles_isolated_context_shared_budget_evidence_and_children(self):
        provider=RolesProvider();value=self.run_agent(provider=provider,mode='team')
        self.assertEqual(value['status'],'completed')
        result=value['result']
        self.assertEqual(result['specialist_calls'],3)
        self.assertEqual(result['usage']['total_tokens'],320)
        self.assertEqual(self.ledger().status()['daily_tokens'],320)
        self.assertEqual(result['citations'],['E1','E2'])
        self.assertEqual(len(provider.calls),4)
        for call in provider.calls[:3]:
            self.assertNotIn('tools',call)
            self.assertNotIn('SPECIALIST_ONLY_ANALYSIS',json.dumps(call))
            self.assertNotIn(str(self.home),json.dumps(call))
            self.assertIn('cache',call['messages'][1]['content'])
        self.assertIn('SPECIALIST_ONLY_ANALYSIS',json.dumps(provider.calls[-1]))
        with WorkStore(self.home/'work.sqlite3') as work:
            children=work.db.execute('SELECT * FROM runs WHERE parent=?',(value['run_id'],)).fetchall()
            self.assertEqual({c['role'] for c in children},{'research','career','life'})
            self.assertTrue(all(c['state']=='completed' for c in children))
            self.assertEqual(len({c['session'] for c in children}),3)
        repeat=RolesProvider()
        self.assertTrue(self.run_agent(provider=repeat,mode='team')['cached'])
        self.assertEqual(repeat.calls,[])

    def test_resume_after_specialist_paid_commit_is_free_and_plan_immutable(self):
        first=RolesProvider();partial=self.run_agent(provider=first,mode='team',step_limit=2)
        self.assertEqual(partial['status'],'checkpointed')
        self.assertEqual(len(first.calls),1)
        second=RolesProvider()
        value=execute(self.home,None,'role-work',resume=True,provider=second)
        self.assertEqual(value['status'],'completed')
        self.assertEqual(len(second.calls),3)
        self.assertEqual(self.ledger().status()['daily_tokens'],320)
        with self.assertRaisesRegex(ValueError,'role_conflict'):
            self.run_agent(mode='life',provider=second)
        with self.assertRaisesRegex(ValueError,'saved_role_plan'):
            execute(self.home,None,'role-work',resume=True,mode='life',provider=second)
        self.assertEqual(len(second.calls),3)

    def test_completed_supervisor_extra_search_does_not_change_paid_specialist_payload(self):
        provider=RolesProvider(search_again=True)
        first=self.run_agent(mode='research',provider=provider,step_limit=5)
        second=RolesProvider(search_again=True)
        value=execute(self.home,None,'role-work',resume=True,provider=second)
        self.assertEqual(value['status'],'completed')
        self.assertLessEqual(value['result']['searches'],3)
        self.assertEqual(len(provider.calls)+len(second.calls),3)

    def test_pause_fences_specialist_inflight_and_unknown_cannot_repeat(self):
        def pause():
            with WorkStore(self.home/'work.sqlite3') as work:
                did=work.list()[0]['id'];work.control(did,'pause')
        provider=RolesProvider(hook=pause)
        with self.assertRaisesRegex(ValueError,'inactive_or_stale'):
            self.run_agent(mode='team',provider=provider)
        self.assertEqual(self.ledger().status()['daily_tokens'],80)
        repeated=RolesProvider()
        state=execute(self.home,None,'role-work',resume=True,provider=repeated)
        self.assertGreater(state['unresolved_executions'],0)
        self.assertEqual(repeated.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            children=work.db.execute('SELECT role,state FROM runs WHERE parent IS NOT NULL').fetchall()
            self.assertEqual(len(children),1)

    def test_source_revocation_before_replay_clears_all_role_results(self):
        value=self.run_agent(mode='team')
        (self.home/'source/cache.md').unlink()
        provider=RolesProvider()
        with self.assertRaises(ValueError):
            execute(self.home,None,'role-work',resume=True,provider=provider)
        self.assertEqual(provider.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertTrue(all(r[0] is None for r in work.db.execute('SELECT result FROM runs')))

    def test_unknown_specialist_call_is_not_retried_and_reservation_retained(self):
        provider=RolesProvider(unknown=True)
        with self.assertRaisesRegex(ValueError,'unknown_no_retry'):
            self.run_agent(mode='career',provider=provider)
        second=RolesProvider()
        state=execute(self.home,None,'role-work',resume=True,provider=second)
        self.assertEqual(second.calls,[])
        self.assertGreater(state['unresolved_executions'],0)
        self.assertEqual(self.ledger().status()['unresolved_calls'],1)

    def test_existing_paid_direct_protocol_cannot_be_upgraded_in_place(self):
        self.run_agent(provider=RolesProvider(),bootstrap=True)
        provider=RolesProvider()
        with self.assertRaisesRegex(ValueError,'role_conflict'):
            self.run_agent(provider=provider,mode='auto')
        self.assertEqual(provider.calls,[])

    def test_invalid_specialist_reference_is_billed_once_and_free_replay_stays_rejected(self):
        class Invalid(RolesProvider):
            def complete(self,payload,secret):
                reply=super().complete(payload,secret)
                reply['content']=json.dumps({'status':'supported','answer':'Wrong [E99]',
                    'citations':['E99'],'uncertainty':'Partial'})
                return reply
        provider=Invalid()
        with self.assertRaises(ValueError):self.run_agent(mode='research',provider=provider)
        with self.assertRaises(ValueError):
            execute(self.home,None,'role-work',resume=True,provider=provider)
        self.assertEqual(len(provider.calls),1)
        self.assertEqual(self.ledger().status()['daily_tokens'],80)

    def test_distinct_domain_goal_does_not_reach_other_specialists(self):
        from personal_asis.domain_context import DomainContexts
        with DomainContexts(self.home) as contexts:
            contexts.set('research','RESEARCH_GOAL_CANARY','',['synthetic'],'research',allow_model=True)
            contexts.set('life','UNSELECTED_LIFE_GOAL_CANARY','',['synthetic'],'life',allow_model=True)
        provider=RolesProvider()
        self.run_agent(mode='team',domain='research',provider=provider)
        self.assertIn('RESEARCH_GOAL_CANARY',json.dumps(provider.calls[0]))
        for call in provider.calls[1:3]:
            self.assertNotIn('RESEARCH_GOAL_CANARY',json.dumps(call))
        self.assertNotIn('UNSELECTED_LIFE_GOAL_CANARY',json.dumps(provider.calls))

    def test_budget_stop_before_specialist_and_no_background_or_budget_increase(self):
        path=self.home/'pa1.json';data=json.loads(path.read_text())
        data['daily_tokens']=1;path.write_text(json.dumps(data))
        provider=RolesProvider()
        with self.assertRaisesRegex(ValueError,'budget_exhausted'):
            self.run_agent(mode='team',provider=provider)
        self.assertEqual(provider.calls,[])
        self.assertEqual(pa1.settings(self.home)['daily_tokens'],1)

"""Synthetic multi-role continuity: isolation, paid replay and revocation."""
import copy,json,shutil,tempfile,unittest
from personal_asis import pa1
from personal_asis.agent import execute,inspect,clean_sessions
from personal_asis.agent_model import ToolMiMo
from personal_asis.domain_context import DomainContexts
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore
from personal_asis.work_history import retrieve_history

class Provider(ToolMiMo):
    def __init__(self):super().__init__('mac','synthetic-model');self.calls=[]
    def credential(self):return 'SYNTHETIC_CREDENTIAL'
    def complete(self,payload,secret):
        self.calls.append(copy.deepcopy(payload));system=payload['messages'][0]['content']
        role=next((r for r,label in [('research','知识研究'),('career','申请与职业'),('life','生活记录与复盘')] if '你是'+label+'专业角色' in system),'supervisor')
        return {'content':json.dumps({'status':'supported','answer':role.upper()+'_CACHE_FINDING [E1][E2]',
            'citations':['E1','E2'],'uncertainty':'Synthetic evidence only'}),'tool_calls':None,
            'finish_reason':'stop','usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}

@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),'Pi required')
class RoleContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name);pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        with DomainContexts(self.home) as store:
            for role in ('research','career','life'):
                store.set(role,role.upper()+'_GOAL_CANARY','',['synthetic'],role,allow_model=True)
    def run_agent(self,key,provider=None,**kw):
        return execute(self.home,'cache',key,['synthetic'],mode='team',provider=provider or Provider(),**kw)
    def test_each_role_gets_only_its_goal_and_history_not_supervisor_or_siblings(self):
        first=self.run_agent('origin',use_context=True)
        provider=Provider();value=self.run_agent('followup',provider,use_context=True,role_history=True)
        for index,role in enumerate(('research','career','life')):
            wire=json.dumps(provider.calls[index],ensure_ascii=False)
            self.assertIn(role.upper()+'_GOAL_CANARY',wire)
            self.assertIn(role.upper()+'_CACHE_FINDING',wire)
            self.assertIn('旧引用已省略',wire)
            for other in {'research','career','life','supervisor'}-{role}:
                self.assertNotIn(other.upper()+'_GOAL_CANARY',wire)
                self.assertNotIn(other.upper()+'_CACHE_FINDING',wire)
            self.assertNotIn(str(self.home),wire)
        wire=json.dumps(provider.calls[-1]);self.assertNotIn('_GOAL_CANARY',wire)
        self.assertTrue(all(len(c['history_used'])==1 for c in value['result']['role_context_used']))
        self.assertEqual(value['result']['usage']['total_tokens'],320)
        self.assertEqual(len(retrieve_history(self.home,'research','cache',['synthetic'],role='research')),2)
    def test_opt_in_and_unapproved_missing_goal_are_explicit_and_do_not_leak(self):
        provider=Provider();self.run_agent('off',provider)
        self.assertNotIn('_GOAL_CANARY',json.dumps(provider.calls))
        with DomainContexts(self.home) as store:
            store.forget('life','forget-life')
            store.set('career','UNAPPROVED_GOAL','',['synthetic'],'private',allow_model=False)
        provider=Provider();value=self.run_agent('limited',provider,use_context=True)
        metadata={v['role']:v for v in value['result']['role_context_used']}
        self.assertTrue(metadata['research']['used']);self.assertFalse(metadata['career']['used']);self.assertFalse(metadata['life']['used'])
        self.assertNotIn('UNAPPROVED_GOAL',json.dumps(provider.calls))
    def test_snapshot_and_paid_resume_are_stable_when_new_history_is_added(self):
        origin=self.run_agent('origin',use_context=True)
        first=Provider();partial=self.run_agent('resume',first,use_context=True,role_history=True,step_limit=2)
        self.assertEqual(partial['status'],'checkpointed');self.assertEqual(len(first.calls),1)
        self.run_agent('newer',use_context=True)
        second=Provider();value=execute(self.home,None,'resume',resume=True,provider=second)
        self.assertEqual(len(second.calls),3)
        self.assertTrue(all(c['history_used'][0]['run_id']==origin['run_id'] for c in value['result']['role_context_used']))
        self.assertTrue(execute(self.home,None,'resume',resume=True,provider=Provider())['cached'])
        with self.assertRaisesRegex(ValueError,'options_conflict'):
            self.run_agent('resume',use_context=True,role_history=False)
    def test_goal_change_clears_affected_parent_children_and_downstream_only(self):
        origin=self.run_agent('origin',use_context=True)
        follower=self.run_agent('follower',use_context=True,role_history=True)
        unrelated=self.run_agent('unrelated')
        with DomainContexts(self.home) as store:store.forget('research','forget-research')
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertTrue(all(r[0] is None for r in work.db.execute('SELECT payload FROM agent_sessions WHERE run IN (?,?)',(origin['run_id'],follower['run_id']))))
            self.assertTrue(all(r[0] is None for r in work.db.execute('SELECT result FROM runs WHERE delegation IN (?,?)',(origin['delegation_id'],follower['delegation_id']))))
            self.assertIsNotNone(work.session(unrelated['run_id']))
        provider=Provider()
        with self.assertRaises(ValueError):execute(self.home,None,'follower',resume=True,provider=provider)
        self.assertEqual(provider.calls,[])
    def test_source_deletion_invalidates_history_and_subsequent_replay_without_new_model(self):
        self.run_agent('origin',use_context=True)
        follower=self.run_agent('follower',use_context=True,role_history=True)
        (self.home/'source/cache.md').unlink();clean_sessions(self.home)
        self.assertEqual(retrieve_history(self.home,'research','cache',['synthetic'],role='research'),[])
        with WorkStore(self.home/'work.sqlite3') as work:self.assertIsNone(work.db.execute('SELECT payload FROM agent_sessions WHERE run=?',(follower['run_id'],)).fetchone()[0])
    def test_current_message_support_ignores_continuity_without_note_reads(self):
        from test_request_intent import Direct
        provider=Direct();value=execute(self.home,'给我鼓励','support',['synthetic'],mode='life',use_context=True,role_history=True,provider=provider)
        self.assertEqual(value['result']['searches'],0);self.assertNotIn('_GOAL_CANARY',json.dumps(provider.calls))

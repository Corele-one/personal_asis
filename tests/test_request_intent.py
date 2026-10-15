import copy,json,shutil,tempfile,unittest
from unittest.mock import patch
from contextlib import closing

from personal_asis import pa1
from personal_asis.agent import execute
from personal_asis.agent_model import ToolMiMo
from personal_asis.request_intent import response_plan,validate_answer
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore


class Direct(ToolMiMo):
    def __init__(self):super().__init__('mac','synthetic-model');self.calls=[]
    def credential(self):return 'SYNTHETIC_CREDENTIAL'
    def complete(self,payload,secret):
        self.calls.append(copy.deepcopy(payload))
        return {'content':json.dumps({'status':'conversational','answer':'你可以先歇一会儿，我愿意听你说。',
            'citations':[],'uncertainty':''}),'tool_calls':None,'finish_reason':'stop',
            'usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}


class IntentTests(unittest.TestCase):
    def test_simple_support_needs_no_notes_but_explicit_history_remains_grounded(self):
        self.assertIsNotNone(response_plan('我最近有点难过，安慰我两句','life'))
        self.assertIsNotNone(response_plan('给我鼓励','auto'))
        self.assertIsNone(response_plan('根据最近三天日记，安慰我两句','life'))
        self.assertIsNone(response_plan('分析历史记录，给出鼓励','auto'))
        self.assertIsNone(response_plan('解释 cache coherence','research'))
        self.assertIsNone(response_plan('安慰我','team'))
        self.assertIsNotNone(response_plan('你好','conversation'))
    def test_direct_reply_cannot_smuggle_evidence_references_or_unknown_schema(self):
        valid={'status':'conversational','answer':'Hello','citations':[],'uncertainty':''}
        for changed in ({'citations':['E1']},{'answer':'You [E1]'},{'status':'supported'},
                        {'answer':''},{'extra':'ignored?'}):
            with self.assertRaises(ValueError):validate_answer(json.dumps({**valid,**changed}))


@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),'Pi required')
class DirectExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name);pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
    def run_agent(self,provider=None,**kwargs):
        return execute(self.home,'我有点难过，安慰我两句','support',['synthetic'],mode='life',
                       provider=provider or Direct(),**kwargs)
    def test_real_pi_direct_reply_never_reads_notes_or_uses_semantic_encoder_and_bills_once(self):
        provider=Direct()
        with patch('personal_asis.agent.build_bundle',side_effect=AssertionError('unexpected_note_read')),\
             patch('personal_asis.pa1.encoder_for',side_effect=AssertionError('unexpected_semantic_load')):
            value=self.run_agent(provider)
        result=value['result']
        self.assertEqual(result['response_kind'],'conversation')
        self.assertEqual(result['searches'],0);self.assertEqual(result['evidence'],[])
        self.assertEqual(result['citations'],[]);self.assertEqual(result['usage']['total_tokens'],80)
        self.assertEqual(len(provider.calls),1);self.assertNotIn('tools',provider.calls[0])
        wire=json.dumps(provider.calls)
        for marker in ('PRIVATE_CANARY','cache coherence',str(self.home)):self.assertNotIn(marker,wire)
        with WorkStore(self.home/'work.sqlite3') as work:
            self.assertEqual(work.session(value['run_id'])['roots'],{})
            self.assertEqual(work.db.execute('SELECT count(*) FROM runs').fetchone()[0],1)
        self.assertTrue(self.run_agent(provider)['cached']);self.assertEqual(len(provider.calls),1)
    def test_paid_direct_step_resumes_in_new_process_contract_without_new_generation(self):
        first=Direct();value=self.run_agent(first,step_limit=1)
        self.assertEqual(value['status'],'checkpointed')
        second=Direct();final=execute(self.home,None,'support',resume=True,provider=second)
        self.assertEqual(final['status'],'completed');self.assertEqual(second.calls,[])
        with closing(pa1.budget(self.home,'mac',pa1.settings(self.home))) as budget:
            self.assertEqual(budget.status()['daily_tokens'],80)
    def test_user_message_reply_does_not_inherit_source_note_permissions(self):
        p=self.home/'sources.yaml';config=json.loads(p.read_text())
        config['sources'][0]['model_providers']=[];p.write_text(json.dumps(config))
        result=self.run_agent()['result']
        self.assertEqual(result['searches'],0)
        self.assertEqual(result['response_kind'],'conversation')
    def test_explicit_domain_or_history_cannot_enter_direct_reply(self):
        with self.assertRaisesRegex(ValueError,'cannot_use_note_context'):
            self.run_agent(domain='life')
    def test_outcome_unknown_direct_reply_cannot_be_retried(self):
        from personal_asis.model_provider import ProviderUnknown
        class Unknown(Direct):
            def complete(self,payload,secret):self.calls.append(payload);raise ProviderUnknown('test')
        provider=Unknown()
        with self.assertRaisesRegex(ValueError,'unknown_no_retry'):self.run_agent(provider)
        second=Direct();result=execute(self.home,None,'support',resume=True,provider=second)
        self.assertGreater(result['unresolved_executions'],0);self.assertEqual(second.calls,[])

    def test_explicit_recent_notes_cannot_expand_scope_when_model_drops_date_words(self):
        from datetime import date,timedelta
        today=date.today()
        for name,when in [('cache.md',today-timedelta(days=100)),('coherence.md',today)]:
            (self.home/'source'/name).write_text('---\ndate: '+when.isoformat()+'\n---\n# Note\n\ncache SYNTHETIC_TIME_EVIDENCE\n')
        from personal_asis.index import Index
        from personal_asis.config import load_config
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:index.reconcile()
        class Timed(Direct):
            def complete(self,payload,secret):
                self.calls.append(copy.deepcopy(payload))
                if 'tools' in payload and not any(m['role']=='tool' for m in payload['messages']):
                    return {'content':None,'tool_calls':[{'id':'more','type':'function','function':{
                        'name':'search_notes','arguments':'{"query":"cache"}'}}],
                        'finish_reason':'tool_calls','usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}
                return {'content':json.dumps({'status':'supported','answer':'Current evidence [E1]',
                    'citations':['E1'],'uncertainty':'Only dated note evidence'}),'tool_calls':None,'finish_reason':'stop',
                    'usage':{'prompt_tokens':70,'completion_tokens':10,'total_tokens':80}}
        first=Timed()
        partial=execute(self.home,'最近三天 cache 日记分析','recent',['synthetic'],mode='life',
            provider=first,bootstrap=True,step_limit=1)
        self.assertEqual(partial['status'],'checkpointed');self.assertEqual(first.calls,[])
        with WorkStore(self.home/'work.sqlite3') as work:
            saved=work.session(partial['run_id'])
            self.assertEqual([e['record_date'] for e in saved['evidence']],[today.isoformat()])
        from personal_asis.retrieval import build_bundle
        resumed=Timed()
        with patch('personal_asis.retrieval_time.question_window',side_effect=AssertionError('range recomputed')),\
             patch('personal_asis.agent.build_bundle',wraps=build_bundle) as lookup:
            final=execute(self.home,None,'recent',resume=True,provider=resumed)
        self.assertEqual(final['status'],'completed')
        self.assertEqual(final['result']['searches'],2)
        self.assertEqual([e['record_date'] for e in final['result']['evidence']],[today.isoformat()])
        self.assertEqual(lookup.call_count,1)
        self.assertEqual(lookup.call_args.kwargs['time_window'],saved['temporal_scope'])
        self.assertEqual(len(resumed.calls),3)

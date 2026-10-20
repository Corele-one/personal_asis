"""Synthetic answer-policy acceptance; no private text or paid providers."""
from datetime import date
import json
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import answer_policy as p, conversation as c, pa1
from personal_asis.conversation_tools import submit, CURRENT_PROTOCOL, PROTOCOL
from personal_asis.config import load_config
from personal_asis.index import Index
from personal_asis.model_provider import validate_answer as legacy_validate
from personal_asis.retrieval import ContextBundle
from test_conversation import Provider, PI_AVAILABLE


def reply(status='conversational', answer='你好', **kw):
    return {'status':status, 'answer':answer, 'uncertainty':'', **kw}


def state(question='给我一个你对我的印象', evidence=None, actions=None):
    return {'answer_policy':p.plan(question), 'question':question,
            'history':[], 'evidence':evidence or [], 'actions':actions or []}


class PolicyTests(unittest.TestCase):
    def test_three_layers_and_week_timezone(self):
        for q, kind in [('你好','conversation'),('你能做什么','conversation'),('给我一个你对我的印象','conversation'),
                        ('我之前做过什么科研','recall'),('总结我过去一个礼拜','recall'),
                        ('官方申请条件','verification'),('删除资料','verification'),('健康诊断','verification')]:
            with self.subTest(q=q):self.assertEqual(p.plan(q)['kind'],kind)
        for q in ['总结我过去一个礼拜','总结一下我过去的一个星期','总结我过去的一周']:
            value=p.plan(q)
            self.assertTrue(value['dated_review'])
            w=value['window']
            self.assertEqual((date.fromisoformat(w['end'])-date.fromisoformat(w['start'])).days,6)
            self.assertEqual(value['timezone'],'Asia/Shanghai')

    def test_subjective_without_note_citations_and_safe_abstention(self):
        result=p.validate(json.dumps(reply('subjective','从你当前的问题看，你似乎乐于听取反馈。')),state())
        self.assertEqual(result['status'],'subjective')
        self.assertEqual(result['citations'],[])
        self.assertIn('暂定印象',result['uncertainty'])
        result=p.validate(json.dumps(reply('insufficient_evidence','UNSUPPORTED_PERSONAL_FACT')),state())
        self.assertEqual(result['status'],'subjective')
        self.assertNotIn('UNSUPPORTED',json.dumps(result))

    def test_known_inline_ids_derive_index_but_unknown_ids_cannot_be_repaired(self):
        s=state(evidence=[{},{}])
        for changes in ({},{'citations':[]},{'citations':['E2','E1','E1']}):
            r=p.validate(json.dumps(reply('partial','观察 [E2, E1]',**changes)),s)
            self.assertEqual(r['citations'],['E1','E2'])
        for changes in ({'answer':'观察 [E999]'},{'citations':['E999']},{'citations':'E1'},{'answer':'观察 [E1-E2]'}):
            with self.subTest(changes=changes),self.assertRaises(p.AnswerValidationError):
                p.validate(json.dumps({**reply(answer='观察 [E1]'),**changes}),s)

    def test_verification_cannot_escape_as_conversation_or_subjective(self):
        self.assertEqual(p.plan('上面第二个展开讲讲', p.plan('官方申请条件'))['kind'],'verification')
        for status in ['conversational','subjective','partial','supported']:
            with self.assertRaisesRegex(ValueError,'verification_requires_sources'):
                p.validate(json.dumps(reply(status,'未经核实的申请条件')),state('官方申请条件',evidence=[{}]))
        r=p.validate(json.dumps(reply('supported','满足条件 [E1]',citations=[])),state('官方申请条件',evidence=[{}]))
        self.assertEqual(r['status'],'supported')
        self.assertEqual(r['citations'],['E1'])

    def test_no_fact_tool_failure_and_denial_are_distinct(self):
        for receipt,expected in [('no_authorized_match','no_fact'),('unavailable','tool_unavailable'),('permission_denied','permission_denied')]:
            s=state('我之前做过什么科研',actions=[{'key':'tool:1','output':{'status':receipt}}])
            r=p.validate(json.dumps(reply('supported','FABRICATED_RESEARCH')),s)
            self.assertEqual(r['status'],expected)
            self.assertNotIn('FABRICATED',json.dumps(r))

    def test_greetings_are_not_personal_recall_but_explicit_self_report_can_be_used(self):
        s=state('我之前做过什么科研')
        s['history']=[{'role':'user','content':'你好'},{'role':'assistant','content':'ASSISTANT_INFERENCE'}]
        r=p.validate(json.dumps(reply('partial','FABRICATED_RESEARCH')),s)
        self.assertEqual(r['status'],'no_fact')
        self.assertNotIn('FABRICATED',json.dumps(r))
        s['history'][0]['content']='我去年参与了缓存一致性课题。'
        r=p.validate(json.dumps(reply('partial','你在本会话自述参与了缓存一致性课题，尚未独立核实。')),s)
        self.assertEqual(r['status'],'partial')

    def test_layered_errors_and_known_need_more_context_schema(self):
        for body,layer in [('not JSON','protocol'),('[]','protocol'),('{"answer":42}','presentation'),
                           ('{"status":[],"answer":"bad status"}','presentation'),
                           (json.dumps(reply(answer='api_key=sk-'+'a'*30)),'policy')]:
            with self.subTest(layer=layer),self.assertRaises(p.AnswerValidationError) as caught:
                p.validate(body,state())
            self.assertEqual(caught.exception.layer,layer)
        r=p.validate('{"status":"need_more_context","reason":"UNTRUSTED","missing_info":[]}',state('总结过去一周'))
        self.assertEqual(r['status'],'no_fact')
        self.assertNotIn('UNTRUSTED',json.dumps(r))

    def test_paired_validation_fixture_does_not_claim_generation_quality(self):
        # Same four model texts and evidence: only validator behavior compared.
        samples=[('你好',reply('conversational','你好'),[]),('你能做什么',reply('conversational','可讨论和检索'),[]),
                 ('给我一个你对我的印象',reply('subjective','你似乎乐于听反馈'),[]),
                 ('总结我过去一个礼拜',reply('partial','只找到一天的学习记录 [E1]',citations=[]),[{}])]
        old_rejected=new_rejected=0
        for q,body,evidence in samples:
            content=json.dumps(body)
            try:
                if body['status']=='conversational':
                    from personal_asis.request_intent import validate_answer
                    validate_answer(json.dumps({**body,'citations':[]}))
                else:legacy_validate({'finish_reason':'stop','tool_calls':None,'content':content},ContextBundle(q,'mimo',evidence,'lexical'))
            except ValueError:old_rejected+=1
            try:p.validate(content,state(q,evidence))
            except ValueError:new_rejected+=1
        self.assertEqual((old_rejected,new_rejected),(2,0))


@unittest.skipUnless(PI_AVAILABLE,'actual Pi required')
class PolicyIntegrationTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.home=pa1.fixture(temporary.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        with c.ConversationStore(self.home) as store:self.sid=store.create()

    def ask(self,q,provider,tid='p1',**kw):
        return submit(self.home,self.sid,q,turn_id=tid,provider=provider,**kw)

    def records(self):
        root=self.home/'source'
        for path in root.glob('*.md'):path.unlink()
        for d,text in [('2026-10-14','我计划研究一致性协议。'),('2026-10-18','我完成了合成仿真报告。'),('2026-01-01','OLD_DATE_CANARY')]:
            (root/(d+'.md')).write_text('# 合成日记\n\n'+text+'\n')
        path=self.home/'sources.yaml';config=json.loads(path.read_text());config['sources'][0]['model_all_files']=True;path.write_text(json.dumps(config))
        with Index(self.home/'index.sqlite3',load_config(path)) as index:index.reconcile()

    def test_greeting_capabilities_impression_and_context_followup_zero_searches(self):
        provider=Provider([reply(answer='你好'),reply(answer='我能讨论问题、检索获准笔记；公开搜索先确认。'),
                           reply('subjective','从本会话看，你似乎很注重可解释性。'),
                           reply(answer='两个方向：1 缓存一致性；2 软硬件协同。'),reply(answer='第二个方向是软硬件协同，可先比较接口开销。')])
        with patch('personal_asis.conversation_tools.build_bundle',side_effect=AssertionError('no notes')):
            for i,q in enumerate(['你好','你能做什么','给我一个你对我的印象','给两个方向','上面第二个方向展开讲讲']):
                r=self.ask(q,provider,'p'+str(i))
                self.assertEqual(r['status'],'completed',r)
                self.assertEqual(r['result']['searches'],0)
        wire=json.dumps(provider.calls[-1],ensure_ascii=False)
        self.assertIn('软硬件协同',wire)
        self.assertEqual(len(provider.calls),5)
        self.assertEqual(c.budget_status(self.home)['daily_tokens'],250)

    def test_weekly_review_uses_frozen_date_inventory_partial_coverage_one_generation(self):
        self.records()
        window={'start':'2026-10-14','end':'2026-10-20','basis':'question','unknown_dates':'excluded'}
        provider=Provider([reply('partial','10月18日的记录提到完成仿真报告 [E2]')])
        with patch('personal_asis.answer_policy.question_window',return_value=window):
            r=self.ask('总结我过去一个礼拜',provider)
        self.assertEqual(r['status'],'completed',r)
        result=r['result'];self.assertEqual(result['status'],'partial')
        self.assertEqual((result['searches'],len(provider.calls)),(1,1))
        self.assertEqual(result['citations'],['E2'])
        coverage=result['answer_metadata']['coverage']
        self.assertEqual(coverage['selected_dates'],['2026-10-14','2026-10-18'])
        self.assertIn('Asia/Shanghai',result['uncertainty'])
        self.assertNotIn('OLD_DATE_CANARY',json.dumps(provider.calls))
        with patch('personal_asis.local_review.build',side_effect=AssertionError('no reread')):
            cached=self.ask('总结我过去一个礼拜',Provider())
        self.assertTrue(cached['cached']);self.assertEqual(cached['new_usage_tokens'],0)

    def test_weekly_no_records_is_no_fact_without_model_assertions(self):
        self.ask('你好',Provider([reply(answer='你好')]),tid='hello')
        provider=Provider([reply('partial','FABRICATED_HISTORY')])
        r=self.ask('总结我过去一个礼拜',provider)
        self.assertEqual(r['status'],'completed',r)
        self.assertEqual(r['result']['status'],'no_fact')
        self.assertNotIn('FABRICATED',json.dumps(r['result']))
        self.assertEqual(r['result']['answer_metadata']['coverage']['selected_passages'],0)

    def test_paired_synthetic_before_after_experience_and_cost(self):
        self.records()
        window={'start':'2026-10-14','end':'2026-10-20','basis':'question','unknown_dates':'excluded'}
        questions=['你好','你能做什么','给我一个你对我的印象','总结我过去一个礼拜']
        metrics={}
        for version in (PROTOCOL,CURRENT_PROTOCOL):
            refused=tokens=searches=ordinary_searches=0;covered=[];prompt_bytes=[]
            for i,q in enumerate(questions):
                with c.ConversationStore(self.home) as store:sid=store.create()
                if i<2:responses=[reply(answer='你好' if i==0 else '可以讨论问题、检索获准资料。',citations=[])]
                elif version==PROTOCOL:responses=[{'tool':'search_notes','arguments':{'query':q}},reply('insufficient_evidence','',citations=[])]
                else:responses=[reply('subjective','仅从这次提问看，你似乎愿意听反馈。') if i==2 else reply('partial','10月18日记录提到完成合成仿真报告 [E2]')]
                provider=Provider(responses)
                with patch('personal_asis.answer_policy.question_window',return_value=window if i==3 else None),patch('personal_asis.conversation_tools.question_window',return_value=window if i==3 else None):
                    r=c.send(self.home,sid,q,protocol=version,provider=provider)
                self.assertEqual(r['status'],'completed',r)
                result=r['result'];refused+=result['status']=='insufficient_evidence'
                tokens+=result['usage_tokens'];searches+=result['searches']
                if i<3:ordinary_searches+=result['searches']
                if i==3:covered=result.get('answer_metadata',{}).get('coverage',{}).get('selected_dates',[])
                prompt_bytes.extend(len(c.dumps({'messages':payload['messages'],'tools':[]}).encode()) for payload in provider.calls)
            metrics[version]={'fixture_refusals':refused,'questions':4,'mean_scripted_usage_tokens':tokens/4,
                              'ordinary_searches':ordinary_searches,'all_searches':searches,'weekly_selected_dates':covered,
                              'maximum_prompt_bytes':max(prompt_bytes)}
        self.assertEqual(metrics[PROTOCOL]['fixture_refusals'],2)
        self.assertEqual(metrics[CURRENT_PROTOCOL]['fixture_refusals'],0)
        self.assertEqual((metrics[PROTOCOL]['ordinary_searches'],metrics[CURRENT_PROTOCOL]['ordinary_searches']),(1,0))
        self.assertEqual((metrics[PROTOCOL]['mean_scripted_usage_tokens'],metrics[CURRENT_PROTOCOL]['mean_scripted_usage_tokens']),(75,50))
        self.assertEqual(metrics[CURRENT_PROTOCOL]['weekly_selected_dates'],['2026-10-14','2026-10-18'])
        self.assertLessEqual(metrics[CURRENT_PROTOCOL]['maximum_prompt_bytes'],8192)
        self.comparison=metrics

    def test_specific_research_recall_cites_actual_record(self):
        provider=Provider([{'tool':'search_notes','arguments':{'query':'cache'}},reply('supported','记录中讨论了缓存一致性 [E1]')])
        r=self.ask('我之前做过什么科研',provider)
        self.assertEqual(r['status'],'completed',r)
        self.assertEqual(r['result']['status'],'partial')
        self.assertEqual(r['result']['citations'],['E1'])
        self.assertIn('cache',r['result']['evidence'][0]['excerpt'])

    def test_invalid_citation_is_structured_failure_saved_paid_step_no_retry(self):
        provider=Provider([reply('subjective','观察 [E99]')])
        r=self.ask('给我一个你对我的印象',provider)
        self.assertEqual(r['status'],'failed')
        self.assertEqual(r['validation_error']['layer'],'attribution')
        self.assertTrue(r['validation_error']['recovery']['paid_response_saved'])
        second=Provider()
        with self.assertRaisesRegex(ValueError,'requires_explicit_resume_or_is_failed'):
            c.send(self.home,self.sid,turn_id='p1',resume=True,provider=second)
        self.assertEqual(second.calls,[])
        self.assertEqual(c.budget_status(self.home)['daily_tokens'],50)

    def test_v1_paid_checkpoint_and_completed_result_keep_original_protocol(self):
        first=Provider([reply(answer='旧协议回复',citations=[])])
        with patch('personal_asis.answer_policy.plan',side_effect=AssertionError('no migration')):
            r=c.send(self.home,self.sid,'你好',turn_id='legacy',protocol=PROTOCOL,provider=first,step_limit=1)
            self.assertEqual(r['status'],'interrupted')
            second=Provider()
            r=c.send(self.home,self.sid,turn_id='legacy',resume=True,provider=second)
        self.assertEqual(r['status'],'completed',r)
        self.assertEqual(r['result']['tools_protocol'],PROTOCOL)
        self.assertEqual(second.calls,[])
        r=submit(self.home,self.sid,'你好',turn_id='legacy',provider=second)
        self.assertTrue(r['cached']);self.assertEqual(second.calls,[])

    def test_v2_checkpoint_replays_prefetch_and_paid_payload_exactly(self):
        self.records()
        first=Provider([reply('partial','记录中的部分内容 [E1]')])
        r=self.ask('总结我过去一个礼拜',first,step_limit=2)
        self.assertEqual(r['status'],'interrupted',r)
        with c.ConversationStore(self.home) as store:
            original=json.loads(store.get(self.sid,'p1')['state'])['actions']
        with patch('personal_asis.local_review.build',side_effect=AssertionError('no reread')),patch('personal_asis.answer_policy.plan',side_effect=AssertionError('frozen')):
            second=Provider();r=c.send(self.home,self.sid,turn_id='p1',resume=True,provider=second)
        self.assertEqual(r['status'],'completed',r)
        self.assertEqual(second.calls,[])
        with c.ConversationStore(self.home) as store:self.assertEqual(json.loads(store.get(self.sid,'p1')['state'])['actions'],original)

    def test_deletion_and_revocation_purge_new_policy_and_dependent_history(self):
        for change in ('delete','revoke'):
            with self.subTest(change=change):
                if change=='revoke':
                    # New independent fixture, no state reuse after source deletion.
                    self.setUp()
                provider=Provider([{'tool':'search_notes','arguments':{'query':'cache'}},reply('partial','片段观察 [E1]')])
                r=self.ask('我之前做过什么科研',provider)
                self.assertEqual(r['status'],'completed',r)
                self.ask('展开讲讲',Provider([reply(answer='暂定讨论')]),'followup')
                if change=='delete':
                    from pathlib import Path
                    from urllib.parse import urlparse,unquote
                    Path(unquote(urlparse(r['result']['evidence'][0]['original_uri']).path)).unlink()
                else:
                    path=self.home/'sources.yaml';config=json.loads(path.read_text());config['sources'][0]['model_providers']=[];path.write_text(json.dumps(config))
                self.assertEqual(c.inspect(self.home,self.sid)['status'],'invalidated')
                with c.ConversationStore(self.home) as store:self.assertTrue(all(row['state'] is None for row in store.turns(self.sid)))

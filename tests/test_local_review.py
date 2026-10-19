from datetime import date
import copy
import json
import shutil
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
import uuid

from personal_asis import agent,pa1
from personal_asis.config import load_pa1_config
from personal_asis.index import Index
from personal_asis.local_review import build,plan
from personal_asis.pi_terminal import handle
from personal_asis.runtime_adapter import PI_DIR
from test_agent_roles import RolesProvider

class ReviewProvider(RolesProvider):
    def complete(self,payload,secret):
        self.calls.append(copy.deepcopy(payload))
        return {'content':json.dumps({'status':'supported','answer':'合成记录显示完成读书，并记录了散步计划 [E1]。',
             'citations':['E1'],'uncertainty':'只依据提供的记录片段。'},ensure_ascii=False),
             'tool_calls':None,'finish_reason':'stop','usage':{'prompt_tokens':70,'completion_tokens':30,'total_tokens':100}}

class ReviewPlanTests(unittest.TestCase):
    def test_natural_week_phrase_routes_to_life_with_explicit_dates(self):
        for query in ('总结一下我过去的一周','复盘我过去一周','回顾我的最近7天'):
            p=plan(query,['study','life'],'auto',date(2026,10,19))
            self.assertEqual(p['window']['start'],'2026-10-13')
            self.assertEqual(p['window']['end'],'2026-10-19')
            self.assertEqual(p['sources'],['life'])
        previous=plan('总结我的上周',['life'],'life',date(2026,10,19))
        self.assertEqual(previous['window']['start'],'2026-10-12')
        self.assertEqual(previous['window']['end'],'2026-10-18')
    def test_explicit_research_and_general_topics_do_not_get_personal_review(self):
        self.assertIsNone(plan('总结一下我过去的一周',['study'],'research',date(2026,10,19)))
        self.assertIsNone(plan('总结一下缓存一致性',['study','life'],'auto',date(2026,10,19)))
        self.assertEqual(plan('总结一下我过去的一周',['study'],'auto',date(2026,10,19))['sources'],['study'])

class ReviewFixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        self.path=self.home/'source'
        self.path.mkdir(exist_ok=True)
        self.query='总结一下我过去的一周'
        self.review=plan(self.query,['synthetic'],'auto',date(2026,10,19))
        config=json.loads((self.home/'sources.yaml').read_text())
        self.root=Path(config['sources'][0]['root'])
        for name,text in [('2026-10-13.md','# 合成日记\n\n完成了阅读合成教材，并列出下次散步计划。\n'),
                          ('2026-10-18.md','# 合成日记\n\n复习了合成课程并记录练习结果。\n'),
                          ('2020-01-01.md','# 旧日记\n\nOLD_OUTSIDE_WINDOW\n'),
                          ('undated.md','# 无日期\n\nUNKNOWN_DATE\n')]:
            (self.root/name).write_text(text)
        config['sources'][0]['model_all_files']=True
        (self.home/'sources.yaml').write_text(json.dumps(config))
        with Index(self.home/'index.sqlite3',load_pa1_config(self.home)) as index:index.reconcile()
    def test_date_selection_does_not_require_summary_words_in_the_diary(self):
        b,c=build(self.home,self.query,self.review)
        self.assertEqual(c['recorded_dates'],['2026-10-13','2026-10-18'])
        self.assertTrue(b.evidence);b.revalidate(self.home)
        body=json.dumps(b.cloud_input(),ensure_ascii=False)
        self.assertNotIn('OLD_OUTSIDE_WINDOW',body);self.assertNotIn('UNKNOWN_DATE',body)
        self.assertLessEqual(len(body.encode()),5400)
        self.assertTrue(c['partial_excerpts']);self.assertFalse(c['dates_without_records_mean_no_activity'])
    def test_revoked_and_conflicting_dates_cannot_be_selected(self):
        (self.root/'2026-10-18.md').write_text('---\ndate: 2020-01-01\n---\nCONFLICTING_DATE\n')
        b,c=build(self.home,self.query,self.review)
        self.assertNotIn('2026-10-18',c['recorded_dates'])
        cfg=json.loads((self.home/'sources.yaml').read_text());cfg['sources'][0]['model_providers']=[]
        (self.home/'sources.yaml').write_text(json.dumps(cfg))
        b,c=build(self.home,self.query,self.review)
        self.assertEqual(b.evidence,[])
    def test_all_seven_dates_fit_without_increasing_prompt_or_token_caps(self):
        for day in range(13,20):
            (self.root/f'2026-10-{day}.md').write_text('# 合成日记\n\n'+('当天记录的合成内容。'*50)+'\n')
        with Index(self.home/'index.sqlite3',load_pa1_config(self.home)) as index:index.reconcile()
        b,c=build(self.home,self.query,self.review)
        self.assertEqual(len(c['selected_dates']),7)
        self.assertTrue(c['all_recorded_dates_represented'])
        self.assertEqual(len(b.evidence),7)
        self.assertLessEqual(len(json.dumps(b.cloud_input(),ensure_ascii=False).encode()),5400)

@unittest.skipUnless(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),
                     'optional Pi packages and Node required')
class ReviewExecutionTests(unittest.TestCase):
    setUp=ReviewFixture.setUp
    def test_weekly_review_is_one_json_generation_and_replays_without_payment(self):
        client=ReviewProvider()
        with patch('personal_asis.pa1.encoder_for',side_effect=AssertionError('no semantic ranking')):
            value=agent.execute(self.home,self.query,'weekly-new',['synthetic'],mode='auto',
                                provider=client,local_text_json=True,review_plan=self.review)
        self.assertEqual(value['status'],'completed');self.assertEqual(len(client.calls),1)
        self.assertEqual(client.calls[0]['response_format'],{'type':'json_object'})
        self.assertNotIn('tools',client.calls[0]);self.assertEqual(value['result']['model_turns'],1)
        self.assertEqual(value['result'].get('specialist_calls',0),0)
        self.assertIn('2026-10-13',value['result']['uncertainty'])
        self.assertIn('不代表没有活动',value['result']['uncertainty'])
        repeat=ReviewProvider()
        self.assertTrue(agent.execute(self.home,None,'weekly-new',resume=True,provider=repeat)['cached'])
        self.assertEqual(repeat.calls,[])
    def test_no_dated_records_returns_coverage_without_calling_model(self):
        p=plan(self.query,['synthetic'],'auto',date(2040,1,1));client=ReviewProvider()
        result=agent.execute(self.home,self.query,'empty-window',['synthetic'],mode='auto',provider=client,review_plan=p)
        self.assertEqual(client.calls,[]);self.assertEqual(result['result']['status'],'insufficient_evidence')
        self.assertEqual(result['result']['review_coverage']['selected_passages'],0)
        self.assertEqual(result['result']['usage']['total_tokens'],0)
    def test_old_paid_bad_json_status_and_resume_do_not_repeat_call(self):
        class Broken(RolesProvider):
            def complete(self,payload,secret):
                self.calls.append(copy.deepcopy(payload))
                return {'content':'{"answer":"invalid "quoted" text"}', 'tool_calls':None,'finish_reason':'stop',
                        'usage':{'prompt_tokens':70,'completion_tokens':30,'total_tokens':100}}
        client=Broken();rid='terminal-'+str(uuid.uuid4())
        cid=handle(self.home,{'action':'new','sources':['synthetic']})['thread']
        from personal_asis.pi_terminal import Chats
        c=Chats(self.home);c.add(cid,rid);c.close()
        with self.assertRaisesRegex(ValueError,':json'):
            agent.execute(self.home,'cache',rid,['synthetic'],mode='research',provider=client)
        for action in ('status','resume','status'):
            response=handle(self.home,{'action':action,'thread':cid})
            self.assertIn('格式错误',response['text']);self.assertIsNone(response['usage'])
            self.assertEqual(response['failure']['stage'],'specialist')
        self.assertEqual(len(client.calls),1)
        with sqlite3.connect(self.home/'pa1.sqlite3') as db:
            self.assertEqual(db.execute('SELECT state,tokens FROM model_calls').fetchall(),[('succeeded',100)])
    def test_new_terminal_specialist_uses_json_mode_but_old_protocol_stays_unchanged(self):
        for key,flag in [('old',False),('new',True)]:
            client=RolesProvider()
            agent.execute(self.home,'cache',key,['synthetic'],mode='research',provider=client,local_text_json=flag)
            self.assertEqual('response_format' in client.calls[0],flag)
            repeat=RolesProvider();agent.execute(self.home,None,key,resume=True,provider=repeat)
            self.assertEqual(repeat.calls,[])

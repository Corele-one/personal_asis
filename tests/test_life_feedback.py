import asyncio
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from personal_asis.life_store import LifeStore
from personal_asis.life_intake import is_entry, source
from personal_asis.life_tracking import LifeTracking, infer, validate
from personal_asis.life_feedback import LifeFeedback
from personal_asis import life_sync, life_projection
from personal_asis.dashboard import server, snapshot
from personal_asis.web_auth import WebAuth


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name).resolve();self.store=LifeStore(self.home/'life.sqlite3');self.addCleanup(self.store.close)
        self.feedback=LifeFeedback(self.store);self.tracking=LifeTracking(self.store)
        self.record=self.tracking.auto(self.store.capture('p','owner','one','/life 阅读完成')[0])

    def request(self,text='这不是我的阅读，请去掉这条阅读记录。',rid=None,revision=None,key='a'):
        return dict(id=key*32,thread='b'*32,text=text,record_id=rid if rid is not None else self.record['id'],revision=revision if revision is not None else self.record['revision'])

    def start(self,**kwargs):
        self.feedback.submit(self.request(**kwargs));return self.feedback.claim()

    def test_memory_kept_but_never_projected_or_automatically_tracked(self):
        r=self.store.capture('p','owner','ordinary','阅读完成，开始学习一份作业要求',capture_source='conversation')[0]
        r=self.tracking.auto(r)
        self.assertNotIn('tracking',r)
        self.assertFalse(is_entry(r));self.assertFalse(life_sync.projected(r))
        exported=self.store.export()['changes'][-1]['record']
        self.assertEqual(exported['text'],r['text']);self.assertFalse(exported['deleted'])
        self.assertEqual(exported['tracking'],dict(habits=[],learning=[]))
        self.assertIn(r['id'],[v['id'] for v in self.store.recent(include_conversation=True)])
        self.assertNotIn(r['id'],[v['id'] for v in self.store.recent()])
        with self.assertRaisesRegex(ValueError,'explicit_life_entry_required'):
            self.tracking.update(r['id'],dict(habits=[dict(habit='reading',status='done',evidence='阅读完成')],learning=[]))

    def test_requirement_cannot_be_recast_as_reading_or_learning_by_selecting_substring(self):
        for text in ('/life 实践作业要求：阅读完成后写报告。','/life 老师要求我读完《合成书》并交作业。',
                     '/life 作业说明要求开始学习合成材料。','/life 阅读代码文档完成。','/life 这是实践作业要求：\n1. 阅读完成后写报告。'):
            self.assertEqual(infer(text),dict(habits=[],learning=[]),text)
        text='/life 实践作业要求：阅读完成后写报告。'
        with self.assertRaisesRegex(ValueError,'self_report_required'):
            validate(dict(habits=[dict(habit='reading',status='done',evidence='阅读完成')],learning=[]),text)
        with self.assertRaisesRegex(ValueError,'self_report_required'):
            validate(dict(habits=[],learning=[dict(phase='start',topic='合成材料',content='开始学习合成材料',blocker='',next_step='',evidence='开始学习合成材料')]),'/life 作业要求开始学习合成材料。')
        self.assertEqual(infer('/life 我读完了《合成书》')['habits'][0]['status'],'done')
        self.assertEqual([h['habit'] for h in infer('/life 我读完了《冥想》')['habits']],['reading'])
        with self.assertRaisesRegex(ValueError,'self_report_required'):
            validate(dict(habits=[],learning=[dict(phase='start',topic='电路',content='开始学习电路',blocker='',next_step='',evidence='准备学习电路')]),'/life 准备学习电路')

    def test_legacy_migration_retains_source_and_corrects_derived_false_positive(self):
        r=dict(self.record);r.pop('capture_source');r['text']='实践作业要求阅读完成后写报告。'
        r['tracking']=dict(habits=[dict(habit='reading',status='done',evidence='阅读完成')],learning=[])
        with self.store.db:self.store.db.execute('UPDATE records SET payload=? WHERE id=?',(json.dumps(r),r['id']))
        result=self.store.reconcile_intake()
        self.assertEqual(result['excluded_conversations'],1);self.assertEqual(result['corrected_tracking'],1)
        corrected=self.store.get(r['id']);self.assertEqual(corrected['text'],r['text'])
        self.assertEqual(corrected['capture_source'],'conversation')
        self.assertEqual(self.tracking.day(r['day'])['habits'][1]['status'],'unknown')
        self.assertEqual(self.store.reconcile_intake()['changed'],0)

    def test_correct_only_derived_record_once_and_show_before_after(self):
        job=self.start()
        effect=self.feedback.correct(job,('p','owner'),action='clear_habit',habit='reading')
        self.assertEqual(len(effect['before']['tracking']['habits']),1)
        self.assertEqual(effect['after']['tracking']['habits'],[])
        self.assertEqual(self.store.get(self.record['id'])['text'],self.record['text'])
        self.assertEqual(self.feedback.correct(job,('p','owner'),action='clear_habit',habit='reading'),effect)
        self.assertEqual(self.store.get(self.record['id'])['revision'],self.record['revision']+1)
        self.feedback.finish(job,reply='已去掉误判的阅读记录。')
        self.assertEqual(self.feedback.thread('b'*32)[0]['state'],'done')
        self.assertEqual(self.tracking.day(self.record['day'])['habits'][1]['status'],'unknown')

    def test_stale_target_owner_change_and_general_chat_cannot_write(self):
        job=self.start()
        with self.assertRaisesRegex(ValueError,'owner_required'):
            self.feedback.correct(job,('p','other'),action='summary',value='错误身份')
        self.store.organize(self.record['id'],kind='journal',summary='另一处更新')
        with self.assertRaisesRegex(ValueError,'record_changed'):
            self.feedback.correct(job,('p','owner'),action='clear_habit',habit='reading')
        self.feedback.finish(job,error='conflict')
        job=self.start(text='你好',revision=self.store.get(self.record['id'])['revision'],key='c')
        with self.assertRaisesRegex(ValueError,'explicit_correction_required'):
            self.feedback.correct(job,('p','owner'),action='clear_habit',habit='reading')

    def test_feedback_evidence_is_attributed_without_rewriting_original_and_sync_validates(self):
        job=self.start(text='其实我今天完成了冥想，阅读是误判，请改正。')
        value=dict(habits=[dict(habit='meditation',status='done',evidence='我今天完成了冥想')],learning=[])
        effect=self.feedback.correct(job,('p','owner'),action='tracking',value=json.dumps(value))
        r=self.store.get(self.record['id']);self.assertEqual(r['text'],self.record['text'])
        self.assertEqual(r['feedback_notes'][0]['text'],job['text'])
        self.assertEqual(self.tracking.day(r['day'])['habits'][0]['status'],'done')
        life_sync.validate_record(self.store.export()['changes'][-1]['record'])
        self.assertEqual(effect['after']['revision'],r['revision'])

    def test_queue_idempotency_busy_and_restart_unknown_never_reclaims_request(self):
        request=self.request();self.feedback.submit(request);self.feedback.submit(request)
        self.assertEqual(len(self.feedback.thread('b'*32)),1)
        with self.assertRaisesRegex(ValueError,'id_conflict'):
            self.feedback.submit(dict(request,text='不同的请求'))
        with self.assertRaisesRegex(ValueError,'busy'):self.feedback.submit(self.request(key='c'))
        job=self.feedback.claim();self.assertEqual(job['id'],request['id'])
        self.feedback.recover();self.assertIsNone(self.feedback.claim())
        self.assertEqual(self.feedback.thread('b'*32)[0]['state'],'unknown')

    def test_excluded_entry_keeps_original_memory_and_removes_only_approved_projection(self):
        state=dict(records={self.record['id']:self.record},applied={})
        vault=self.home/'vault';vault.mkdir()
        # A habit-only entry has no Freewrite prose; use a reflective entry instead.
        r=self.store.capture('p','owner','second','/life 合成的生活感想')[0]
        state=dict(records={r['id']:r},applied={})
        files,changes=life_sync.plan(state,vault,'.');life_sync.apply(files);state['applied'].update(changes)
        job=self.start(rid=r['id'],revision=r['revision'],text='这条不该进入随记，请移除。')
        self.feedback.correct(job,('p','owner'),action='exclude_entry')
        state['records'][r['id']]=self.store.get(r['id'])
        files,_=life_sync.plan(state,vault,'.')
        self.assertNotIn('合成的生活感想',files[0]['after'])
        self.assertIn('合成的生活感想',(vault/(r['day']+'.md')).read_text())
        self.assertEqual(self.store.get(r['id'])['text'],r['text'])
        self.assertIn(r['id'],[v['id'] for v in self.store.recent(include_conversation=True)])

    def test_correction_keeps_other_learning_topics_and_requires_explicit_entry_exclusion(self):
        r=self.store.capture('p','owner','learning','/life 我学习了主题甲和主题乙')[0]
        items=[dict(phase='progress',topic=topic,content='我学习了主题甲和主题乙',blocker='',next_step='',evidence='我学习了主题甲和主题乙') for topic in ('主题甲','主题乙')]
        r=self.tracking.update(r['id'],dict(habits=[],learning=items))
        job=self.start(text='主题甲这条记录错了，请去掉。',rid=r['id'],revision=r['revision'])
        with self.assertRaisesRegex(ValueError,'learning_topic_required'):
            self.feedback.correct(job,('p','owner'),action='clear_learning')
        with self.assertRaisesRegex(ValueError,'explicit_journal_exclusion_required'):
            self.feedback.correct(job,('p','owner'),action='exclude_entry')
        self.feedback.correct(job,('p','owner'),action='clear_learning',value='主题甲')
        self.assertEqual([item['topic'] for item in self.store.get(r['id'])['tracking']['learning']],['主题乙'])

    def test_http_feedback_requires_session_csrf_same_origin_and_returns_private_queue(self):
        with WebAuth(self.home,otp_required=False) as auth:
            token=auth.bootstrap()['setup_token'];auth.setup_finish(token,'synthetic-long-password','','fixture')
        srv=server(self.home,'https://dashboard.example',0)
        thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
        headers={'Host':'dashboard.example','X-Forwarded-Proto':'https','Origin':'https://dashboard.example'}
        c=http.client.HTTPConnection('127.0.0.1',srv.server_port)
        self.addCleanup(c.close)
        try:
            c.request('GET','/api/feedback?thread='+'b'*32,headers=headers)
            r=c.getresponse();self.assertEqual(r.status,401);r.read()
            c.request('POST','/auth/login',json.dumps(dict(password='synthetic-long-password')),headers)
            r=c.getresponse();cookie=r.getheader('Set-Cookie').split(';')[0];csrf=json.loads(r.read())['csrf']
            authenticated=dict(headers,Cookie=cookie)
            for wrong in ({}, {'X-CSRF-Token':csrf,'Origin':'https://evil.example'}):
                c.request('POST','/api/feedback',json.dumps(self.request()),dict(authenticated,**wrong))
                r=c.getresponse();self.assertEqual(r.status,403);r.read()
            c.request('POST','/api/feedback',json.dumps(self.request()),dict(authenticated,**{'X-CSRF-Token':csrf}))
            r=c.getresponse();self.assertEqual(r.status,202);r.read()
            c.request('GET','/api/feedback?thread='+'b'*32,headers=authenticated)
            r=c.getresponse();data=json.loads(r.read());self.assertEqual(len(data['messages']),1)
            self.assertNotIn(str(self.home),json.dumps(data));self.assertEqual(r.getheader('Cache-Control'),'no-store')
        finally:
            srv.shutdown();srv.server_close();thread.join()


class IntakePluginTests(unittest.TestCase):
    def setUp(self):
        from test_life_bedtime import PluginTests
        PluginTests.setUp(self);self.event=lambda *a,**kw:PluginTests.event(self,*a,**kw)

    def test_ordinary_chat_is_memory_and_model_cannot_turn_it_into_diary_or_activity(self):
        async def run():
            event=self.event('实践作业要求阅读完成后写报告')
            self.assertEqual([r async for r in self.bot.collect(event)],[])
            memories=self.bot.store.recent(include_conversation=True)
            self.assertEqual(len(memories),1);self.assertEqual(source(memories[0]),'conversation')
            self.assertFalse(life_sync.projected(memories[0]))
            self.assertEqual(await self.bot.track(event),'explicit_life_entry_required')
            self.assertEqual(await self.bot.organize(event,'journal','误判'),'explicit_life_entry_required')
            self.assertEqual(len(json.loads(await self.bot.recent(event))),1)
            self.assertEqual(self.bot.store.recent(),[])
        asyncio.run(run())

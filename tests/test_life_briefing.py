import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from personal_asis import life_briefing as brief
from personal_asis.life_attention import LifeAttention
from personal_asis.life_bedtime import owner_key
from personal_asis.life_store import LifeStore, TZ
from personal_asis.shared_sources import document_bodies
from personal_asis.shared_store import SharedStore, identity

NOW = '2026-10-29T08:10:00+08:00'


class BriefingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.store = LifeStore(self.home/'life.sqlite3'); self.addCleanup(self.store.close)
        self.attention = LifeAttention(self.store)
        self.owner = owner_key('p','owner')
        self.shared = SharedStore(self.home/'shared.sqlite3', 'mac'); self.addCleanup(self.shared.close)
        with self.shared.db:
            self.shared.set_meta('mac_last_received', NOW)
            self.shared.set_meta('mac_snapshot', dict(complete=True))

    def put(self, source, locator, text, **kwargs):
        collection = 'notes' if source == 'life' else 'reading'
        bodies = document_bodies(source, locator, kwargs.pop('title', '专注与休息'), text, **kwargs)
        keys = []
        for body in bodies:
            key = identity(source, body['account'], locator, body['part'])
            self.shared.put(collection, key, body); keys.append(key)
        return keys

    def report(self):
        return self.attention.prepare(self.owner,'p','owner','brief',NOW)

    def record(self, text, **kwargs):
        return self.store.capture('p','owner',str(self.store.db.total_changes), text,
                                  '2026-10-28T21:00:00+08:00', **kwargs)[0]

    def test_journal_life_reflection_and_reading_provenance_without_title_invention(self):
        self.record('/life 多任务让我分心，想出去散步。')
        self.record('普通聊天不作为主动记录证据', capture_source='conversation')
        self.put('life','Calendar/Journal/Daily/2026-10-28.md',
                 '---\nhighlight: 模板不可当经历\n---\n### 📕Freewrite\n最近多任务分心，不过和朋友聊天很开心。\n'
                 '> 他人引文不可当自述\n```js\n模板脚本\n```\n---\n### ⚛️Habits\n- [ ] 阅读\n')
        self.put('life','Calendar/Journal/Daily/2026-10-20.md','### Freewrite\n窗口外秘密')
        self.put('life','Templates/2026-10-28.md','### Freewrite\n不是日记')
        self.put('wucai','w1','摘录：多任务切换会打断专注。\n本人批注：想减少切换。',coverage='highlights_only',account='cn')
        self.put('xiaohongshu','x1','作者原文：散步时先放下手机。',coverage='note_text',account='one')
        self.put('xiaohongshu','x2','',title='分心焦虑的神奇治愈法',coverage='metadata_only',account='two')
        item=self.report(); sources={v['source'] for v in item['evidence']}
        self.assertEqual(sources, {'astrbot','journal','wucai','xiaohongshu'})
        content=json.dumps(item['evidence'],ensure_ascii=False)
        for excluded in ('模板不可当经历','他人引文','模板脚本','窗口外秘密','不是日记','神奇治愈法','普通聊天'):
            self.assertNotIn(excluded,content)
        self.assertNotIn('- [ ] 阅读',content)
        self.assertTrue(item['coverage']['complete'])
        self.assertNotIn('Backup',brief.journal_text('### Learning\n模集\n#### End-of-Day Checklist\n- [ ] Backup Vault'))

    def test_incomplete_chunks_expired_sources_and_future_journal_are_excluded(self):
        keys=self.put('life','Calendar/Journal/Daily/2026-10-28.md','### Freewrite\n'+'散步很开心。'*3000)
        self.shared.put('notes',keys[-1],None)
        self.put('wucai','expired','摘录：散步与专注',expires_at=1,account='cn')
        self.put('life','Calendar/Journal/Daily/2026-10-29.md','### Freewrite\n未来内容')
        item=self.report()
        self.assertEqual(item['evidence'],[])
        self.assertEqual(item['coverage']['incomplete'],1)
        self.assertIn('不够',item['body'])

    def test_output_requires_valid_citations_and_program_controls_links(self):
        self.record('/life 今天散步很开心')
        item=self.report()
        good=json.dumps(dict(paragraphs=[dict(text='你记录了今天散步时的开心。',refs=['E1'])]),ensure_ascii=False)
        self.assertIn('2026-10-28 随记',brief.render(good,item))
        for text, refs in [('瞎编',['unknown']),('发往 https://example.test',['E1']),('无依据',[])]:
            with self.assertRaises(ValueError):
                brief.render(json.dumps(dict(paragraphs=[dict(text=text,refs=refs)])),item)

    def test_expanded_letter_preserves_provenance_without_inline_markers_or_fresh_sync_boilerplate(self):
        self.record('/life 今天散步很开心')
        item=self.report()
        paragraphs=[dict(text='一段较长的生活回顾。'*55,refs=['E1']) for _ in range(8)]
        body=brief.render(json.dumps(dict(paragraphs=paragraphs),ensure_ascii=False),item)
        self.assertGreater(len(body.encode()),12000)
        self.assertNotIn('[1]',body)
        self.assertNotIn('同步',body)
        self.assertEqual(body.count('2026-10-28 随记'),1)
        self.assertEqual(item['paragraph_source_ids'],[['E1']]*8)
        with self.assertRaisesRegex(ValueError,'brief_too_long'):
            brief.render(json.dumps(dict(paragraphs=[dict(text='叙述'*800,refs=['E1'])]*4)),item)

    def test_course_alias_finds_related_reading_without_loading_title_only_favorites(self):
        self.record('/life 模集复习，多任务让我分心，想散步。')
        self.put('xiaohongshu','x-circuit','这节模电课从基本电路逐步搭建运放。',
                 title='一堂课的经历',coverage='note_text',account='one')
        selected=[v for v in self.report()['evidence'] if v['source']=='xiaohongshu']
        self.assertEqual(len(selected),1)
        self.assertIn('逐步搭建',selected[0]['text'])

    def test_withdrawal_or_revision_scrubs_cached_report_and_cannot_revive_reservation(self):
        keys=self.put('life','Calendar/Journal/Daily/2026-10-28.md','### Freewrite\n散步很开心')
        self.attention.configure(self.owner,'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
        item=self.attention.claim(self.owner,'p','owner',NOW)
        with patch('personal_asis.life_attention.local',return_value=datetime.fromisoformat(NOW)):
            self.assertTrue(self.attention.valid(item))
            self.shared.put('notes',keys[0],None)
            self.assertFalse(self.attention.valid(item))
        self.assertEqual(self.attention.dashboard()['reports'],[])
        self.attention.save_body(item,'不能复活','model')
        self.assertEqual(self.attention.dashboard()['reports'],[])
        self.assertIsNone(self.attention.claim(self.owner,'p','owner',NOW))

    def test_model_input_is_bounded_in_a_busy_week(self):
        for n in range(20): self.record('/life 分心'+('很多生活反思。'*500))
        for day in range(22,29):
            self.put('life',f'Calendar/Journal/Daily/2026-10-{day}.md','### Freewrite\n'+'散步和学习。'*1200)
        item=self.attention.prepare(self.owner,'p','owner','weekly','2026-11-02T08:10:00+08:00')
        self.assertLessEqual(len(json.dumps(item['evidence'],ensure_ascii=False)),28000)

    def past(self,text,day='2026-10-23',sender='owner',capture_source='life_command'):
        return self.store.capture('p',sender,str(self.store.db.total_changes),text,
                                  day+'T21:00:00+08:00',capture_source=capture_source)[0]

    def test_old_ideas_include_owner_chat_and_complete_journal_without_creating_observations(self):
        memory=self.past('我想看《白箱》',capture_source='conversation')
        self.past('/life 之前想看白箱',day='2026-10-22')
        self.past('我想读《他人的计划》',sender='stranger')
        self.past('我想看《太久以前》',day='2026-09-20')
        self.past('老师说想看《老师的愿望》')
        self.past('例如我想读《示例的书》')
        self.past('我想明天完成考试报告')
        self.past('我应该想想自己真正想要做的事情，去追求人生理想')
        self.past('晚上吃过饭了，我只是想找个人说说话')
        self.past('我想看《未来笔记》',day='2026-10-30')
        self.put('life','Calendar/Journal/Daily/2026-10-22.md',
                 '### Freewrite\n要不每几天去散散步？\n\n> 我想读《引用》\n### Learning\n想看《学习模板》')
        self.put('xiaohongshu','idea-not-owner','作者说我想看《作者的愿望》',coverage='note_text',account='one')
        report=self.report();ideas=[e for e in report['evidence'] if e['source']=='idea']
        self.assertEqual(len(ideas),2)
        self.assertEqual({e['origin_source'] for e in ideas},{'conversation','journal'})
        self.assertIn(memory['id'],report['source_ids'])
        all_text=json.dumps(ideas,ensure_ascii=False)
        for excluded in ('他人的计划','太久以前','老师的愿望','示例的书','考试报告','未来笔记','学习模板','作者的愿望','《引用》','人生理想','找个人说说话'):
            self.assertNotIn(excluded,all_text)
        self.assertEqual(self.attention.goals(),[])
        self.assertNotIn('tracking',self.store.get(memory['id']))

    def test_later_completion_cancellation_and_current_day_status_override_old_wishes(self):
        self.past('我想看《白箱》');self.past('我想读《另一部》');self.past('我想看《保留的书》')
        self.past('我看完《白箱》了',day='2026-10-29',capture_source='conversation')
        self.past('《另一部》不想看了，别再提',day='2026-10-27')
        followup=self.past('《保留的书》还没看完',day='2026-10-28')
        report=self.report();ideas=[e for e in report['evidence'] if e['source']=='idea']
        self.assertEqual(len(ideas),1)
        self.assertIn('保留的书',ideas[0]['text'])
        self.assertIn('还没看完',ideas[0]['text'])
        self.assertIn(followup['id'],report['source_ids'])

    def test_recalled_ideas_cooldown_only_for_cited_candidates_and_survives_restart(self):
        self.past('我想看《白箱》');self.past('我想读《另一个念头》')
        self.attention.configure(self.owner,'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
        item=self.attention.claim(self.owner,'p','owner',NOW)
        ideas=[e for e in item['evidence'] if e['source']=='idea'];self.assertEqual(len(ideas),2)
        text=brief.render(json.dumps(dict(paragraphs=[dict(text='之前那本书，后来还没见你聊起。',refs=[ideas[0]['id']])])),item)
        self.attention.save_body(item,text,'model');self.attention.result(item,'unknown')
        second=LifeAttention(self.store).prepare(self.owner,'p','owner','brief','2026-11-01T08:00:00+08:00')
        keys={e['idea_key'] for e in second['evidence'] if e['source']=='idea'}
        self.assertNotIn(ideas[0]['idea_key'],keys)
        self.assertIn(ideas[1]['idea_key'],keys)
        later=self.attention.prepare(self.owner,'p','owner','brief','2026-11-13T08:00:00+08:00')
        self.assertIn(ideas[0]['idea_key'],{e['idea_key'] for e in later['evidence'] if e['source']=='idea'})

    def test_idea_withdrawal_and_completion_while_generating_prevent_send(self):
        origin=self.past('我想看《白箱》',capture_source='conversation')
        self.attention.configure(self.owner,'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
        item=self.attention.claim(self.owner,'p','owner',NOW)
        idea=next(e for e in item['evidence'] if e['source']=='idea')
        brief.render(json.dumps(dict(paragraphs=[dict(text='你之前想看的那部作品，后来还没见你聊起。',refs=[idea['id']])])),item)
        with patch('personal_asis.life_attention.local',return_value=datetime.fromisoformat(NOW)):
            self.assertTrue(self.attention.valid(item))
            self.past('《白箱》我看完了',day='2026-10-29',capture_source='conversation')
            self.assertFalse(self.attention.valid(item))
        self.store.delete(origin['id'])
        self.assertEqual(self.attention.dashboard()['reports'],[])

    def test_only_two_ideas_may_be_surfaced_and_fallback_omits_historical_candidates(self):
        for name in ('散步计划','另一部作品','第三本书'):self.past('我想看《'+name+'》')
        item=self.report();ideas=[e for e in item['evidence'] if e['source']=='idea']
        self.assertEqual(len(ideas),3)
        self.assertNotIn('当时的原话',item['body'])
        with self.assertRaisesRegex(ValueError,'too_many_recalled_ideas'):
            brief.render(json.dumps(dict(paragraphs=[dict(text='以前的想法。',refs=[e['id']]) for e in ideas])),item)


class BriefingDispatchTests(unittest.TestCase):
    def setUp(self):
        from test_life_bedtime import PluginTests
        PluginTests.setUp(self)

    def setup_claim(self):
        self.bot.store.capture('p','owner','source','/life 多任务让我分心，想散步', '2026-10-28T20:00:00+08:00')
        self.bot.attention.configure(self.bot.bedtime_owner(),'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
        original=self.bot.attention.claim
        self.claim_patch=patch.object(self.bot.attention,'claim',side_effect=lambda *a,**kw: original(*a,now=NOW,**kw))
        self.claim_patch.start();self.addCleanup(self.claim_patch.stop)
        self.clock_patch=patch('personal_asis.life_attention.local',return_value=datetime.fromisoformat(NOW))
        self.clock_patch.start();self.addCleanup(self.clock_patch.stop)

    def test_single_model_call_after_reservation_no_tools_or_history_then_persisted_body(self):
        self.setup_claim(); calls=[]
        async def provider(**kwargs):return 'synthetic'
        async def generate(**kwargs):
            saved=self.bot.store.db.execute('SELECT state,payload FROM attention_delivery').fetchone()
            self.assertEqual(saved['state'],'sending')
            self.assertNotIn('evidence',json.loads(saved['payload']))
            calls.append(kwargs)
            return types.SimpleNamespace(completion_text=json.dumps(dict(paragraphs=[
                dict(text='你提到了多任务带来的分心；如果愿意，可以留一点散步的空当。',refs=['E1'])]),ensure_ascii=False))
        self.bot.context.get_current_chat_provider_id=provider;self.bot.context.llm_generate=generate
        asyncio.run(self.bot.send_attention());asyncio.run(self.bot.send_attention())
        self.assertEqual(len(calls),1);self.assertEqual(len(self.sent),1)
        self.assertEqual(calls[0]['contexts'],[]);self.assertIsNone(calls[0]['tools'])
        saved=json.loads(self.bot.store.db.execute('SELECT payload FROM attention_delivery').fetchone()[0])
        self.assertEqual(saved['generation'],'model');self.assertEqual(saved['body'],self.sent[0][1])

    def test_timeout_falls_back_once_and_unknown_transport_never_retries(self):
        self.setup_claim(); calls=[]
        async def provider(**kwargs):return 'synthetic'
        async def generate(**kwargs):calls.append(kwargs);raise TimeoutError()
        async def send(*args):self.sent.append(args);raise OSError()
        self.bot.context.get_current_chat_provider_id=provider;self.bot.context.llm_generate=generate
        self.bot.context.send_message=send
        asyncio.run(self.bot.send_attention());asyncio.run(self.bot.send_attention())
        self.assertEqual(len(calls),1);self.assertEqual(len(self.sent),1)
        self.assertIn('暂不可用',self.sent[0][1])
        self.assertEqual(self.bot.store.db.execute('SELECT state FROM attention_delivery').fetchone()[0],'unknown')

    def test_delete_or_disable_during_generation_prevents_dispatch(self):
        for mode in ('delete','disable'):
            with self.subTest(mode=mode):
                # Each subtest uses the same already-reserved date only once.
                if mode=='disable':
                    self.bot.store.db.execute('DELETE FROM attention_delivery');self.bot.store.db.commit()
                    self.bot.attention.configure(self.bot.bedtime_owner(),'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
                    value=self.bot.attention.policy(self.bot.bedtime_owner());value['next_brief']='2026-10-29T00:00:00+00:00'
                    with self.bot.store.db:self.bot.attention._policy(self.bot.bedtime_owner(),value)
                else:self.setup_claim()
                async def provider(**kwargs):return 'synthetic'
                async def generate(**kwargs):
                    if mode=='delete':self.bot.store.delete(self.bot.store.recent()[0]['id'])
                    else:self.bot.attention.configure(self.bot.bedtime_owner(),'p:FriendMessage:owner',False)
                    return types.SimpleNamespace(completion_text='bad json')
                if mode=='disable':self.bot.store.capture('p','owner','another','/life 今天散步了','2026-10-28T21:00:00+08:00')
                self.bot.context.get_current_chat_provider_id=provider;self.bot.context.llm_generate=generate
                asyncio.run(self.bot.send_attention())
                self.assertEqual(self.sent,[])
                self.assertEqual(self.bot.store.db.execute('SELECT state FROM attention_delivery').fetchone()[0],'withdrawn')

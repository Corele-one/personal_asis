import asyncio
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.life_store import LifeStore
from personal_asis.life_bedtime import owner_key
from personal_asis.life_tracking import LifeTracking, infer, validate
from personal_asis.life_attention import LifeAttention
from personal_asis import life_projection, life_sync


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.store = LifeStore(self.root/'life.sqlite3'); self.addCleanup(self.store.close)
        self.tracking = LifeTracking(self.store)
        self.attention = LifeAttention(self.store)
        self.owner = owner_key('p', 'owner')
        self.origin = 'p:FriendMessage:owner'

    def record(self, text, message='one', at='2026-10-26T10:00:00+08:00'):
        return self.tracking.auto(self.store.capture('p','owner',message,text,at)[0])

    def test_plans_negation_quotes_questions_and_goodnight_are_not_completion(self):
        for text in ('打算阅读', '我想冥想', '明天运动完成打卡', '朋友锻炼完成了吗？', '他说“冥想完成”', '晚安', '我不冥想了'):
            with self.subTest(text=text):
                self.assertFalse(any(h['status']=='done' for h in infer(text)['habits']))
        self.assertEqual(infer('今天还没锻炼')['habits'][0]['status'],'not_done')
        with self.assertRaisesRegex(ValueError,'completion_not_supported|self_report_required'):
            validate(dict(habits=[dict(habit='reading',status='done',evidence='计划阅读')],learning=[]),'计划阅读')

    def test_evidence_required_and_native_correction_survives_replay(self):
        r=self.record('今天冥想了十分钟')
        self.assertEqual(r['tracking']['habits'][0]['status'],'done')
        with self.assertRaisesRegex(ValueError,'evidence_required'):
            self.tracking.update(r['id'],dict(habits=[dict(habit='reading',status='done',evidence='编造')],learning=[]))
        changed=self.tracking.update(r['id'],dict(habits=[],learning=[]))
        self.assertEqual(self.tracking.auto(self.store.get(r['id'])),changed)
        self.assertEqual(len(self.store.recent()),1)

    def test_open_learning_topics_start_end_pairing_and_unknown_habits(self):
        a=self.record('开始学习 锁相环的环路稳定性')
        b=self.record('学完了 锁相环的环路稳定性','two','2026-10-26T11:00:00+08:00')
        day=self.tracking.day('2026-10-26')
        self.assertEqual(day['learning'][1]['start_record_id'],a['id'])
        self.assertEqual(day['open_sessions'],[])
        self.assertTrue(all(h['status']=='unknown' for h in day['habits']))
        self.assertNotIn('duration',day['learning'][1])
        self.store.delete(b['id'])
        self.assertEqual(self.tracking.day('2026-10-26')['open_sessions'],[a['id']])

    def test_later_plan_does_not_erase_completion_and_explicit_negative_can_correct(self):
        self.record('阅读完成')
        self.record('准备阅读','two','2026-10-26T11:00:00+08:00')
        self.assertEqual(self.tracking.day('2026-10-26')['habits'][1]['status'],'done')
        self.record('今天其实没有阅读','three','2026-10-26T12:00:00+08:00')
        self.assertEqual(self.tracking.day('2026-10-26')['habits'][1]['status'],'not_done')

    def test_goals_explicit_selection_cap_replay_pause_stop_and_owner(self):
        with self.assertRaisesRegex(ValueError,'explicit_focus'):
            r=self.record('今天有点累');self.attention.goal(self.owner,r['id'],title='多休息')
        goals=[]
        for n in range(3):
            r=self.record('帮我持续跟进目标'+str(n),str(n))
            goals.append(self.attention.goal(self.owner,r['id'],title='目标'+str(n)))
            self.attention.goal(self.owner,r['id'],title='目标'+str(n))
        self.assertEqual(len(self.attention.goals(self.owner)),3)
        r=self.record('帮我跟进第四件事','four')
        with self.assertRaisesRegex(ValueError,'three_active'):
            self.attention.goal(self.owner,r['id'],title='第四')
        self.attention.goal(self.owner,r['id'],goal_id=goals[0]['id'],status='stopped')
        self.attention.goal(self.owner,r['id'],title='第四')
        selected=self.store.get(goals[0]['source_ids'][0])
        replay=self.attention.goal(self.owner,selected['id'],title='目标0')
        self.assertEqual(replay['status'],'stopped')
        with self.assertRaisesRegex(ValueError,'owner_required'):
            self.attention.goal(owner_key('p','other'),r['id'],title='错误身份')
        with self.assertRaisesRegex(ValueError,'goal_not_found'):
            self.attention.goal(self.owner,r['id'],goal_id='unknown',title='不存在')

    def enable(self, at='2026-10-26T12:00:00+08:00'):
        return self.attention.configure(self.owner,self.origin,True,at)

    def claim(self, at):
        return self.attention.claim(self.owner,'p','owner',at)

    def test_three_day_morning_window_no_immediate_send_no_backlog_and_unknown_no_retry(self):
        self.enable()
        for at in ('2026-10-26T08:30:00+08:00','2026-10-29T07:59:59+08:00','2026-10-29T09:00:00+08:00'):
            self.assertIsNone(self.claim(at))
        item=self.claim('2026-10-29T08:20:00+08:00')
        self.assertEqual(item['origin'],self.origin)
        self.attention.result(item,'unknown')
        self.assertIsNone(self.claim('2026-10-29T08:21:00+08:00'))
        second=LifeStore(self.root/'life.sqlite3')
        try:
            restarted=LifeAttention(second)
            self.assertIsNone(restarted.claim(self.owner,'p','owner','2026-10-29T08:40:00+08:00'))
        finally:second.close()
        self.assertIsNone(self.claim('2026-10-31T08:10:00+08:00'))
        self.assertIsNone(self.attention.claim(owner_key('p','other'),'p','other','2026-11-01T08:10:00+08:00'))

    def test_monday_previous_week_overrides_regular_brief_and_pause_controls(self):
        self.enable()
        self.attention.pause(self.owner,'week','2026-10-28T11:00:00+08:00')
        self.assertIsNone(self.claim('2026-10-29T08:20:00+08:00'))
        item=self.claim('2026-11-02T08:00:00+08:00')
        self.assertEqual(item['kind'],'weekly')
        self.assertEqual((item['start'],item['end']),('2026-10-26','2026-11-01'))
        self.assertIsNone(self.claim('2026-11-02T08:10:00+08:00'))
        self.assertEqual(self.attention.policy(self.owner)['next_brief'],'2026-11-05T00:00:00+00:00')

    def test_prepared_report_is_grounded_in_specific_learning_and_missing_data(self):
        r=self.record('今天学习了差分放大器，卡在共模增益，下次先画小信号模型')
        item=dict(phase='end',topic='差分放大器',content='学习差分放大器',blocker='共模增益',next_step='先画小信号模型',evidence=r['text'])
        self.tracking.update(r['id'],dict(habits=[],learning=[item]))
        report=self.attention.prepare(self.owner,'p','owner','brief','2026-10-29T08:10:00+08:00')
        self.assertIn('共模增益',report['body']);self.assertIn('□ 先画小信号模型',report['body'])
        self.assertIn('pi_sync',report['body']);self.assertIn('不够',report['body'])
        self.assertNotIn('未完成阅读',report['body'])

    def test_goal_followup_only_once_per_update_and_snooze_preserves_window(self):
        self.enable()
        r=self.record('帮我持续跟进实验进展')
        self.attention.goal(self.owner,r['id'],title='实验',next_step='核对测量条件',now='2026-10-26T12:00:00+08:00')
        item=self.claim('2026-10-27T08:10:00+08:00');self.assertIsNotNone(item)
        self.assertIn('核对测量条件',item['body'])
        self.assertIsNone(self.claim('2026-10-28T08:10:00+08:00'))
        self.attention.pause(self.owner,'later','2026-10-30T08:10:00+08:00')
        self.assertIsNone(self.claim('2026-10-30T08:20:00+08:00'))
        self.assertIsNone(self.claim('2026-10-30T10:20:00+08:00'))

    def test_delete_scrubs_tracking_goals_and_prepared_content_from_exports(self):
        self.enable()
        r=self.record('帮我持续跟进独特合成实验，冥想完成')
        self.attention.goal(self.owner,r['id'],title='独特合成实验',now='2026-10-26T12:00:00+08:00')
        self.assertIsNotNone(self.claim('2026-10-29T08:10:00+08:00'))
        self.store.delete(r['id'])
        self.assertNotIn('独特合成',json.dumps(self.store.export(),ensure_ascii=False))
        self.assertEqual(self.attention.goals(),[])
        self.assertEqual(self.attention.dashboard()['reports'],[])

    def test_managed_projection_checks_template_preserves_manual_and_recovers_after_crash(self):
        r=self.record('冥想完成，开始学习 半导体能带')
        state=dict(records={r['id']:r},applied={})
        vault=self.root/'vault';vault.mkdir();note=vault/'2026-10-26.md'
        original='### ⚛️Habits\n#### ☀️Morning\n- [ ] 🧘 meditation\n#### Habits\n- [x] 📖 reading\n### 📖Learning\n我的原笔记\n### 其他\n保留\n'
        note.write_text(original)
        files,receipts=life_projection.plan(state,vault,'.')
        self.assertEqual(note.read_text(),original)
        after=files[0]['after'];self.assertIn('- [x] 🧘 meditation',after)
        self.assertIn('半导体能带',after);self.assertIn('我的原笔记',after);self.assertIn('### 其他\n保留',after)
        life_sync.apply(files);state['activity_applied']=receipts
        self.assertEqual(life_projection.plan(state,vault,'.')[0],[])
        state['records'][r['id']]=self.store.delete(r['id'])
        files,_=life_projection.plan(state,vault,'.');life_sync.apply(files)
        self.assertIn('- [ ] 🧘 meditation',note.read_text())
        self.assertIn('- [x] 📖 reading',note.read_text())
        self.assertNotIn('半导体能带',note.read_text())

    def test_projection_moves_day_stops_for_damaged_markers_and_concurrent_edits(self):
        r=self.record('开始学习 电流镜');state=dict(records={r['id']:r},applied={})
        vault=self.root/'vault';vault.mkdir()
        files,receipts=life_projection.plan(state,vault,'.');life_sync.apply(files);state['activity_applied']=receipts
        state['records'][r['id']]=self.store.organize(r['id'],kind='journal',occurred_at='2026-10-25T21:00:00+08:00')
        files,_=life_projection.plan(state,vault,'.');self.assertEqual(len(files),2)
        files[0]['path'].write_text('预览后修改')
        with self.assertRaisesRegex(ValueError,'reconfirmation'):life_sync.apply(files)
        note=vault/'2026-10-25.md';note.write_text('<!-- asis-learning:2026-10-25:start -->\n不完整\n')
        with self.assertRaisesRegex(ValueError,'damaged_activity'):life_projection.plan(state,vault,'.')

    def test_pi_sync_previews_all_activity_and_skip_then_confirm_is_idempotent(self):
        import contextlib, io
        home=self.root/'home';home.mkdir();profile=self.root/'profile';profile.mkdir();vault=self.root/'vault';vault.mkdir()
        (home/'sources.yaml').write_text(json.dumps({'node_id':'mac','sources':[{'id':'life','root':str(vault),'policy':'private','index':True}]}))
        (profile/'life-sync.json').write_text(json.dumps(dict(enabled=True,host='owner@example.test',daily_directory='Daily',journal_layout_mode='plain')))
        r=self.record('冥想完成，开始学习 电源噪声分析')
        def fetch(config,state):state['records'][r['id']]=r;state['cursor']=2
        with patch.object(life_sync,'pull',side_effect=fetch),patch.object(life_sync,'publish_status'),contextlib.redirect_stdout(io.StringIO()) as shown:
            with patch('builtins.input',return_value=''):
                self.assertEqual(life_sync.startup(home,profile,interactive=True),'skipped')
            self.assertFalse((vault/'Daily').exists())
            self.assertIn('⚛️Habits',shown.getvalue());self.assertIn('电源噪声分析',shown.getvalue())
            with patch('builtins.input',return_value='确认写入'):
                self.assertEqual(life_sync.startup(home,profile,interactive=True),'applied')
            with patch('builtins.input') as ask:
                self.assertEqual(life_sync.startup(home,profile,interactive=True),'up_to_date');ask.assert_not_called()
        raw=(vault/'Daily/2026-10-26.md').read_text()
        self.assertNotIn('<!-- asis-learning:',raw)
        self.assertEqual(raw.count('#### 电源噪声分析'),1)
        self.assertIn('activity_applied',json.loads((profile/'life-sync-cache.json').read_text()))


class TrackingPluginTests(unittest.TestCase):
    def setUp(self):
        from test_life_bedtime import PluginTests
        PluginTests.setUp(self)
        self.event=lambda *a,**kw: PluginTests.event(self,*a,**kw)

    def test_native_tool_preserves_other_observations_and_rejects_stranger(self):
        async def run():
            event=self.event('/life 冥想完成，开始学习版图设计')
            self.bot.capture(event)
            result=await self.bot.track(event,learning_json='[]')
            self.assertIn('saved_on',result)
            r=self.bot.store.recent()[0]
            self.assertEqual(len(r['tracking']['habits']),1)
            self.assertEqual(r['tracking']['learning'],[])
            self.assertEqual(await self.bot.track(self.event('/life 冥想完成',owner=False)), 'owner_or_capture_required')
        asyncio.run(run())

    def test_pause_not_captured_and_private_sender_dispatch_uses_persisted_reservation(self):
        async def run():
            self.bot.attention.configure(self.bot.bedtime_owner(),'p:FriendMessage:owner',True,'2026-10-26T12:00:00+08:00')
            [reply async for reply in self.bot.collect(self.event('这周别问'))]
            self.assertEqual(self.bot.store.recent(),[])
            # A fixture controls time and transport. No real platform send or model.
            item=dict(owner=self.bot.bedtime_owner(),origin='p:FriendMessage:owner',day='2026-10-29',body='合成简报')
            with patch.object(self.bot.attention,'claim',return_value=item) as claim,patch.object(self.bot.attention,'result') as result:
                await self.bot.send_attention()
                self.assertEqual(self.sent[-1],('p:FriendMessage:owner','合成简报'))
                result.assert_called_once_with(item,'sent')
        asyncio.run(run())

    def test_existing_goal_is_available_in_native_request_without_new_authorization(self):
        import types
        async def run():
            event=self.event('帮我持续跟进电路实验')
            goal=json.loads(await self.bot.focus(event,'电路实验',next_step='核对测量条件'))
            req=types.SimpleNamespace(system_prompt='')
            await self.bot.instructions(event,req)
            self.assertIn(goal['id'],req.system_prompt)
            self.assertIn('无需重新创建目标',req.system_prompt)
        asyncio.run(run())

    def test_tracking_failure_preserves_honest_original_receipt(self):
        event=self.event('/life 冥想完成')
        with patch.object(self.bot.tracking,'auto',side_effect=ValueError('synthetic derived failure')):
            self.bot.capture(event)
        self.assertEqual(event.get_extra('life_capture_status'),'saved')
        self.assertEqual(self.bot.store.recent()[0]['text'],event.message_str)

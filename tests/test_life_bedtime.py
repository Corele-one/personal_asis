import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from personal_asis.life_bedtime import BedtimeReminder, is_goodnight, nudge_text, owner_key
from personal_asis.life_store import LifeStore


class BedtimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'life.sqlite3'
        self.store = LifeStore(self.path)
        self.addCleanup(self.store.close)
        self.rule = BedtimeReminder(self.store)
        self.owner = owner_key('p', 'owner')
        self.origin = 'p:FriendMessage:owner'

    def enable(self, at='2026-10-21T23:00:00+08:00'):
        return self.rule.set_enabled(self.owner, self.origin, True, at)

    def test_default_off_and_no_early_nudge(self):
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00'))
        self.enable()
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T00:59:59+08:00'))
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00'))

    def test_unknown_and_crash_are_not_retries_but_next_nudge_continues(self):
        self.enable()
        item = self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00')
        second = LifeStore(self.path)
        try:
            restarted = BedtimeReminder(second)
            self.assertIsNone(restarted.claim(self.owner, '2026-10-22T01:09:59+08:00'))
            restarted.result(item, 'unknown')
            self.assertIsNotNone(restarted.claim(self.owner, '2026-10-22T01:10:00+08:00'))
            self.assertEqual(second.db.execute('SELECT state FROM bedtime_delivery WHERE due=?', (item['due'],)).fetchone()[0], 'unknown')
        finally:
            second.close()

    def test_repeated_enable_does_not_reset_active_schedule(self):
        self.enable()
        self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00')
        self.enable('2026-10-22T01:03:00+08:00')
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T01:05:00+08:00'))
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-22T01:10:00+08:00'))

    def test_never_stops_at_morning_or_next_midnight_without_goodnight(self):
        self.enable()
        for at in ('2026-10-22T01:00:00+08:00', '2026-10-22T08:00:00+08:00',
                   '2026-10-22T15:00:00+08:00', '2026-10-23T00:00:00+08:00'):
            self.assertIsNotNone(self.rule.claim(self.owner, at))

    def test_downtime_sends_one_current_nudge_without_backlog(self):
        self.enable()
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-22T12:02:00+08:00'))
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T12:02:01+08:00'))
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T12:07:00+08:00'))
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-22T12:12:00+08:00'))

    def test_upgrade_extends_existing_followup_and_preserves_goodnight(self):
        self.enable()
        self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00')
        with self.store.db:
            self.store.db.execute("UPDATE bedtime_policy SET next_due='2026-10-21T17:05:00+00:00'")
        upgraded = BedtimeReminder(self.store)
        self.assertIsNone(upgraded.claim(self.owner, '2026-10-22T01:09:59+08:00'))
        self.assertIsNotNone(upgraded.claim(self.owner, '2026-10-22T01:10:00+08:00'))
        upgraded.goodnight(self.owner, self.origin, '2026-10-22T01:11:00+08:00')
        expected = upgraded.status(self.owner)
        self.assertEqual(BedtimeReminder(self.store).status(self.owner), expected)

    def test_nudge_rotation_survives_restart_without_creating_records(self):
        self.enable()
        first = self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00')
        second = BedtimeReminder(self.store).claim(self.owner, '2026-10-22T01:10:00+08:00')
        self.assertEqual((first['number'], second['number']), (1, 2))
        self.assertNotEqual(nudge_text(first), nudge_text(second))
        self.assertIn('晚安', nudge_text(first))
        self.assertNotIn('/life', nudge_text(second))
        self.assertEqual(self.store.export()['changes'], [])

    def test_personalization_uses_only_current_night_owner_learning(self):
        from personal_asis.life_tracking import LifeTracking
        record, _ = self.store.capture('p', 'owner', 'study', '/life 开始学习模拟电路',
            '2026-10-21T23:00:00+08:00')
        LifeTracking(self.store).auto(record)
        record = self.store.get(record['id'])
        item = dict(at='2026-10-21T17:00:00+00:00', number=1)
        render = lambda records: nudge_text(item, records, platform='p', sender='owner')
        self.assertIn('模拟电路', render([record]))
        for changes in (dict(sender='other'), dict(platform='other'), dict(deleted=True),
                        dict(capture_source='conversation'), dict(occurred_at='2026-10-20T15:00:00+00:00'),
                        dict(occurred_at='2026-10-21T18:00:00+00:00'), dict(tracking={})):
            self.assertNotIn('模拟电路', render([dict(record, **changes)]), changes)

    def test_evening_and_post_midnight_goodnight_skip_same_night(self):
        for at in ('2026-10-21T23:30:00+08:00', '2026-10-22T00:30:00+08:00'):
            with self.subTest(at=at):
                self.owner = owner_key('p', at)
                self.enable()
                self.rule.goodnight(self.owner, self.origin, at)
                self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00'))
                self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-23T01:00:00+08:00'))

    def test_goodnight_after_deadline_stops_and_next_night_resumes(self):
        self.enable()
        self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00')
        self.rule.goodnight(self.owner, self.origin, '2026-10-22T02:32:00+08:00')
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T11:00:00+08:00'))
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-23T01:00:00+08:00'))

    def test_replayed_goodnight_does_not_silence_next_night(self):
        self.enable()
        self.rule.goodnight(self.owner, self.origin, '2026-10-21T23:00:00+08:00', 'same-message')
        self.rule.goodnight(self.owner, self.origin, '2026-10-22T23:00:00+08:00', 'same-message')
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-23T01:00:00+08:00'))

    def test_disable_persists_and_reenable_honors_goodnight(self):
        self.enable()
        self.rule.goodnight(self.owner, self.origin, '2026-10-21T23:30:00+08:00')
        self.rule.set_enabled(self.owner, self.origin, False, '2026-10-21T23:31:00+08:00')
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00'))
        self.enable('2026-10-21T23:32:00+08:00')
        self.assertIsNone(self.rule.claim(self.owner, '2026-10-22T01:00:00+08:00'))
        self.assertIsNotNone(self.rule.claim(self.owner, '2026-10-23T01:00:00+08:00'))

    def test_owner_binding_changes_cannot_dispatch_previous_owner(self):
        self.enable()
        self.assertIsNone(self.rule.claim(owner_key('p', 'other'), '2026-10-22T01:00:00+08:00'))
        with self.assertRaises(ValueError): owner_key('', 'owner')
        self.assertEqual(self.store.export()['changes'], [])
        self.assertEqual(self.store.claim_reminders('2026-10-23T01:00:00+08:00'), [])

    def test_only_unambiguous_full_message_goodnights(self):
        for text in ('晚安', '睡觉了', '我准备睡觉了。', '晚安，睡觉了🌙', '去睡觉啦', '我睡了'):
            self.assertTrue(is_goodnight(text), text)
        for text in ('还没睡觉', '昨晚睡觉了', '晚安是什么意思', '他说“晚安”', '晚安？', '明天提醒我说晚安', '/life sleep off', '不说晚安', '我要学习'):
            self.assertFalse(is_goodnight(text), text)


class PluginTests(unittest.TestCase):
    def setUp(self):
        # Synthetic API only; deployed-SDK validation is performed separately.
        from personal_asis import life_store, life_bedtime, bootstrap_context, personal_profile, life_tracking, life_attention, life_intake
        modules = {name: types.ModuleType(name) for name in ('astrbot', 'astrbot.api', 'astrbot.api.event', 'astrbot.api.star', 'synthetic_life_plugin')}
        decorator = lambda *a, **kw: lambda fn: fn
        modules['astrbot.api'].logger = types.SimpleNamespace(warning=lambda *a: None)
        modules['astrbot.api.event'].filter = types.SimpleNamespace(event_message_type=decorator,
            EventMessageType=types.SimpleNamespace(ALL=1), on_llm_request=decorator, command=decorator, llm_tool=decorator)
        modules['astrbot.api.event'].AstrMessageEvent = object
        class Chain:
            def message(self, text): return text
        modules['astrbot.api.event'].MessageChain = Chain
        class Star:
            def __init__(self, context): self.context = context
        modules['astrbot.api.star'].Star = Star
        modules['astrbot.api.star'].Context = object
        modules['astrbot.api.star'].register = decorator
        modules['synthetic_life_plugin'].__path__ = []
        modules.update({'synthetic_life_plugin.life_store': life_store,
                        'synthetic_life_plugin.life_bedtime': life_bedtime,
                        'synthetic_life_plugin.bootstrap_context': bootstrap_context,
                        'synthetic_life_plugin.personal_profile': personal_profile})
        modules.update({'synthetic_life_plugin.life_tracking': life_tracking,
                        'synthetic_life_plugin.life_attention': life_attention, 'synthetic_life_plugin.life_intake': life_intake})
        mocked = patch.dict(sys.modules, modules); mocked.start(); self.addCleanup(mocked.stop)
        path = Path(__file__).resolve().parents[1] / 'integrations/astrbot_plugin_life_agent/main.py'
        spec = importlib.util.spec_from_file_location('synthetic_life_plugin.main', path)
        mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.sent = []
        async def send(origin, message): self.sent.append((origin, message)); return True
        self.conversation = object()
        async def current(origin): return 'synthetic-conversation'
        async def get_conversation(origin, cid):
            self.assertEqual(origin, 'p:FriendMessage:owner')
            self.assertEqual(cid, 'synthetic-conversation')
            return self.conversation
        manager = types.SimpleNamespace(get_curr_conversation_id=current, get_conversation=get_conversation)
        with patch.object(Path, 'home', return_value=Path(self.tmp.name)):
            self.bot = mod.LifeAgent(types.SimpleNamespace(send_message=send, conversation_manager=manager),
                                     dict(owner_platform='p', owner_id='owner'))
        self.addCleanup(self.bot.store.close)

    def event(self, text, owner=True, private=True):
        extras = {}
        return types.SimpleNamespace(message_str=text, message_obj=types.SimpleNamespace(message_id='synthetic-message'),
            unified_msg_origin='p:FriendMessage:owner', is_private_chat=lambda: private,
            get_platform_id=lambda: 'p', get_sender_id=lambda: 'owner' if owner else 'other',
            plain_result=lambda text: text, stop_event=lambda: None,
            set_extra=lambda key,value: extras.update({key:value}), get_extra=lambda key: extras.get(key),
            request_llm=lambda **kwargs: dict(native_request=kwargs))

    def collect(self, event):
        async def run(): return [r async for r in self.bot.collect(event)]
        return asyncio.run(run())

    def test_natural_goodnight_records_sleep_once_without_model(self):
        event = self.event('睡觉了')
        self.assertIn('已记下', self.collect(event)[0])
        self.assertLess(len(self.collect(event)[0]), 40)
        self.collect(event)
        rows = self.bot.store.recent()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['kind'], 'sleep_bed')
        self.assertEqual(rows[0]['text'], '睡觉了')

    def test_strangers_and_groups_cannot_stop_rule_or_create_records(self):
        for event in (self.event('晚安', owner=False), self.event('晚安', private=False)):
            self.assertEqual(self.collect(event), [])
        self.assertIsNone(self.bot.bedtime.status(self.bot.bedtime_owner())['last_goodnight'])
        self.assertEqual(self.bot.store.recent(), [])

    def test_capture_disabled_still_honors_goodnight_without_saving_body(self):
        self.bot.config['capture_enabled'] = False
        self.assertIn('睡前记录未保存', self.collect(self.event('晚安'))[0])
        self.assertEqual(self.bot.store.recent(), [])
        self.assertIsNotNone(self.bot.bedtime.status(self.bot.bedtime_owner())['last_goodnight'])

    def test_status_command_after_astrbot_strips_slash_is_not_a_journal(self):
        for text in ('/life', 'life', 'life sleep', 'life sleep off'):
            self.assertEqual(self.collect(self.event(text)), [])
        self.assertEqual(self.bot.store.recent(), [])

    def test_prefixed_goodnight_alias_is_sleep_record_instead_of_status(self):
        async def run():
            replies = [r async for r in self.bot.life(self.event('life 我睡了'), '我睡了')]
            self.assertIn('已记下', replies[0])
            self.assertEqual(self.bot.store.recent()[0]['kind'], 'sleep_bed')
        asyncio.run(run())

    def test_prefixed_journal_preserves_whole_text_and_native_conversation(self):
        async def run():
            event = self.event('life 今天 完成实验\n但有些累，想聊聊。')
            replies = [r async for r in self.bot.life(event, '今天', '完成实验')]
            self.assertEqual(replies[0], '已记下。')
            req = replies[1]['native_request']
            self.assertEqual(req['prompt'], '今天 完成实验\n但有些累，想聊聊。')
            self.assertIs(req['conversation'], self.conversation)
            self.assertEqual(self.bot.store.recent()[0]['text'], event.message_str)
            prompt = types.SimpleNamespace(system_prompt='')
            await self.bot.instructions(event, prompt)
            self.assertIn('不重复回执', prompt.system_prompt)
            # life_organize on the same message must update the existing record.
            await self.bot.organize(event, 'journal', '合成日常整理')
            self.assertEqual(len(self.bot.store.recent()), 1)
        asyncio.run(run())

    def test_capture_disabled_prefixed_journal_still_converses_without_ack(self):
        async def run():
            self.bot.config['capture_enabled'] = False
            event = self.event('life 今天有些累')
            replies = [r async for r in self.bot.life(event, '今天有些累')]
            self.assertEqual(len(replies), 1)
            self.assertIn('native_request', replies[0])
            self.assertEqual(self.bot.store.recent(), [])
            req = types.SimpleNamespace(system_prompt='')
            await self.bot.instructions(event, req)
            self.assertIn('不得声称已记录', req.system_prompt)
        asyncio.run(run())

    def test_storage_failure_is_honest_but_does_not_block_conversation(self):
        import sqlite3
        async def run():
            event=self.event('life 今天有些累')
            with patch.object(self.bot.store,'capture',side_effect=sqlite3.OperationalError('synthetic unavailable')):
                replies=[r async for r in self.bot.life(event,'今天有些累')]
            self.assertEqual(replies[0],'这条暂时没存上。')
            self.assertIn('native_request',replies[1])
            req=types.SimpleNamespace(system_prompt='')
            await self.bot.instructions(event,req)
            self.assertIn('不得声称已记录',req.system_prompt)
        asyncio.run(run())

    def test_reserved_management_never_becomes_journal_or_model_request(self):
        async def run():
            replies = [r async for r in self.bot.life(self.event('life delete'), 'delete')]
            self.assertEqual(replies, ['用法：/life delete 完整记录ID'])
            replies = [r async for r in self.bot.life(self.event('life 今天的日记'), '今天的日记')]
            self.assertIn('native_request', replies[-1])
            self.assertEqual(len(self.bot.store.recent()), 1)
            replies = [r async for r in self.bot.life(self.event('life list'), 'list')]
            self.assertTrue(all(isinstance(r, str) for r in replies))
        asyncio.run(run())

    def test_prefixed_journal_is_owner_only(self):
        async def run():
            for event in (self.event('life 今天有些累', owner=False), self.event('life 今天有些累', private=False)):
                self.assertEqual([r async for r in self.bot.life(event, '今天有些累')], [])
            self.assertEqual(self.bot.store.recent(), [])
        asyncio.run(run())

    def test_approved_profile_is_owner_only_and_forget_removes_it(self):
        from test_personal_profile import fixture
        from personal_asis.personal_profile import load
        async def run():
            path=self.bot.home/'personal-profile.json'
            path.write_text(__import__('json').dumps(fixture()))
            for owner in (False,True):
                req=types.SimpleNamespace(system_prompt='')
                await self.bot.instructions(self.event('你好',owner=owner),req)
                self.assertEqual('合成学习计划' in req.system_prompt,owner)
            context=await self.bot.life_context(self.event('过去的目标是什么'))
            self.assertIn('study/Plan/synthetic.md',context)
            [r async for r in self.bot.life(self.event('life forget-context'),'forget-context')]
            self.assertIsNone(load(path))
        asyncio.run(run())

    def test_commands_toggle_and_dispatch_through_bound_private_origin(self):
        async def run():
            event = self.event('/life sleep on')
            replies = [r async for r in self.bot.life(event, 'sleep', 'on')]
            self.assertIn('已开启', replies[0])
            with self.bot.store.db:
                self.bot.store.db.execute("UPDATE bedtime_policy SET next_due='2000-01-01T00:00:00+00:00'")
            async def stop_after_tick(_): raise asyncio.CancelledError()
            with patch('asyncio.sleep', side_effect=stop_after_tick):
                with self.assertRaises(asyncio.CancelledError): await self.bot.reminders()
            self.assertEqual(len(self.sent), 1)
            self.assertEqual(self.sent[0][0], 'p:FriendMessage:owner')
            self.assertNotIn('/life sleep off', self.sent[0][1])
            self.assertIn('每 10 分钟', replies[0])
            [r async for r in self.bot.life(event, 'sleep', 'off')]
            self.assertFalse(self.bot.bedtime.status(self.bot.bedtime_owner())['enabled'])
        asyncio.run(run())

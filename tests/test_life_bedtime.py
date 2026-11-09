from contextlib import closing
import asyncio
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from personal_asis.life_bedtime import retire, is_goodnight, owner_key
from personal_asis.life_store import LifeStore


class BedtimeRetirementTests(unittest.TestCase):
    def test_retirement_preserves_receipts_and_records_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'life.sqlite3'
            with closing(LifeStore(path)) as store:
                store.db.executescript("CREATE TABLE bedtime_policy(owner TEXT, enabled INTEGER, last_goodnight TEXT);"
                    "INSERT INTO bedtime_policy VALUES('owner',1,'self-report');"
                    "CREATE TABLE bedtime_delivery(state TEXT); INSERT INTO bedtime_delivery VALUES('unknown');")
                record, _ = store.capture('p','owner','old','晚安','2026-11-08T23:00:00+08:00', capture_source='bedtime')
                retire(store)
                self.assertEqual(store.db.execute('SELECT enabled FROM bedtime_policy').fetchone()[0], 0)
                self.assertEqual(store.get(record['id']), record)
            with closing(LifeStore(path)) as store:
                retire(store)
                self.assertEqual(tuple(store.db.execute('SELECT * FROM bedtime_policy').fetchone()), ('owner',0,'self-report'))
                self.assertEqual(store.db.execute('SELECT state FROM bedtime_delivery').fetchone()[0], 'unknown')


class PluginTests(unittest.TestCase):
    def setUp(self):
        # Synthetic API only; deployed-SDK validation is performed separately.
        from personal_asis import life_store, life_images, life_bedtime, bootstrap_context, personal_profile, life_tracking, life_attention, life_intake, life_briefing, wucai_chat, model_display, chat_status
        modules = {name: types.ModuleType(name) for name in ('astrbot', 'astrbot.api', 'astrbot.api.event', 'astrbot.api.star', 'synthetic_life_plugin')}
        decorator = lambda *a, **kw: lambda fn: fn
        modules['astrbot.api'].logger = types.SimpleNamespace(warning=lambda *a: None)
        modules['astrbot.api.event'].filter = types.SimpleNamespace(event_message_type=decorator,
            EventMessageType=types.SimpleNamespace(ALL=1), on_llm_request=decorator, on_llm_response=decorator,
            on_decorating_result=decorator, command=decorator, llm_tool=decorator)
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
                        'synthetic_life_plugin.life_images': life_images,
                        'synthetic_life_plugin.life_bedtime': life_bedtime,
                        'synthetic_life_plugin.bootstrap_context': bootstrap_context,
                        'synthetic_life_plugin.personal_profile': personal_profile})
        modules.update({'synthetic_life_plugin.life_tracking': life_tracking,
                        'synthetic_life_plugin.model_display': model_display, 'synthetic_life_plugin.chat_status': chat_status,
                        'synthetic_life_plugin.life_attention': life_attention, 'synthetic_life_plugin.life_intake': life_intake,
                        'synthetic_life_plugin.life_briefing': life_briefing, 'synthetic_life_plugin.wucai_chat': wucai_chat})
        agent_path = Path(__file__).resolve().parents[1] / 'integrations/astrbot_plugin_life_agent/briefing_agent.py'
        agent_spec = importlib.util.spec_from_file_location('synthetic_life_plugin.briefing_agent', agent_path)
        # Load after the synthetic package has been registered below.
        mocked = patch.dict(sys.modules, modules); mocked.start(); self.addCleanup(mocked.stop)
        agent_module = importlib.util.module_from_spec(agent_spec); agent_spec.loader.exec_module(agent_module)
        agent_mock = patch.dict(sys.modules, {'synthetic_life_plugin.briefing_agent': agent_module})
        agent_mock.start(); self.addCleanup(agent_mock.stop)
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
        with patch.object(Path, 'home', return_value=Path(self.tmp.name).resolve()):
            self.bot = mod.LifeAgent(types.SimpleNamespace(send_message=send, conversation_manager=manager),
                                     dict(owner_platform='p', owner_id='owner'))
        self.addCleanup(self.bot.store.close)

    def event(self, text, owner=True, private=True):
        extras = {}
        return types.SimpleNamespace(message_str=text, message_obj=types.SimpleNamespace(message_id='synthetic-message'),
            unified_msg_origin='p:FriendMessage:owner', is_private_chat=lambda: private,
            get_platform_id=lambda: 'p', get_sender_id=lambda: 'owner' if owner else 'other',
            get_messages=lambda: [],
            plain_result=lambda text: text, stop_event=lambda: None,
            set_extra=lambda key,value: extras.update({key:value}), get_extra=lambda key: extras.get(key),
            request_llm=lambda **kwargs: dict(native_request=kwargs))

    def collect(self, event):
        async def run(): return [r async for r in self.bot.collect(event)]
        return asyncio.run(run())

    def test_natural_goodnight_continues_normal_chat_without_sleep_capture(self):
        event = self.event('睡觉了')
        self.assertEqual(self.collect(event), [])
        row = self.bot.store.get(self.bot.rid(event))
        self.assertEqual(row['capture_source'], 'conversation')
        self.assertFalse(hasattr(self.bot, 'bedtime'))

    def test_strangers_groups_and_capture_disabled_do_not_save_goodnight(self):
        for event in (self.event('晚安', owner=False), self.event('晚安', private=False)):
            self.assertEqual(self.collect(event), [])
        self.bot.config['capture_enabled'] = False
        self.assertEqual(self.collect(self.event('晚安')), [])
        self.assertEqual(self.bot.store.recent(), [])

    def test_status_command_after_astrbot_strips_slash_is_not_a_journal(self):
        for text in ('/life', 'life', 'life sleep', 'life sleep off'):
            self.assertEqual(self.collect(self.event(text)), [])
        self.assertEqual(self.bot.store.recent(), [])

    def test_prefixed_goodnight_alias_is_sleep_record_instead_of_status(self):
        async def run():
            replies = [r async for r in self.bot.life(self.event('life goodnight'), 'goodnight')]
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

    def test_retired_commands_never_enable_or_dispatch(self):
        async def run():
            for action in ('on', 'off', ''):
                replies = [r async for r in self.bot.life(self.event('/life sleep '+action), 'sleep', action)]
                self.assertIn('已移除', replies[0])
            async def stop_after_tick(_): raise asyncio.CancelledError()
            with patch('asyncio.sleep', side_effect=stop_after_tick):
                with self.assertRaises(asyncio.CancelledError): await self.bot.reminders()
            self.assertEqual(self.sent, [])
            if self.bot.attention_worker:
                await self.bot.attention_worker
        asyncio.run(run())

    def test_tools_follow_real_entry_intent_and_do_not_mutate_shared_catalog(self):
        class Tools:
            def __init__(self):
                self.tools = [types.SimpleNamespace(name=n) for n in ('life_track','life_organize','shared_knowledge')]
            def remove_tool(self, name): self.tools = [t for t in self.tools if t.name != name]
        async def run():
            catalog = Tools()
            for text, expected in (
                ('讨论PWA架构，生活工具为什么误触发？', {'shared_knowledge'}),
                ('他说“提醒我提交材料”，这条系统规则合理吗？', {'shared_knowledge'}),
                ('> 明天提醒我提交材料\n分析这个示例', {'shared_knowledge'}),
                ('明天晚上八点提醒我提交材料', {'life_organize','shared_knowledge'}),
                ('我明天八点有课，提醒我七点半出门', {'life_organize','shared_knowledge'}),
                ('过十分钟提醒我喝水', {'life_organize','shared_knowledge'}),
                ('不要再提醒我喝水', {'shared_knowledge'}),
                ('/life 今天完成实验', {'life_track','life_organize','shared_knowledge'})):
                req = types.SimpleNamespace(system_prompt='',func_tool=catalog)
                await self.bot.instructions(self.event(text), req)
                self.assertEqual({t.name for t in req.func_tool.tools}, expected, text)
                self.assertNotIn('催睡是', req.system_prompt)
                self.assertEqual(len(catalog.tools), 3)
            event = self.event('/life 伪任务')
            event.set_extra('cron_job', {'id':'synthetic'})
            req = types.SimpleNamespace(system_prompt='',func_tool=catalog)
            await self.bot.instructions(event, req)
            self.assertEqual([t.name for t in req.func_tool.tools], ['shared_knowledge'])
            self.assertEqual(await self.bot.organize(event, 'journal', '伪自述'), 'explicit_life_entry_required')
            self.assertEqual(await self.bot.track(event), 'explicit_life_entry_required')
        asyncio.run(run())

"""Run in the installed AstrBot interpreter; never send platform messages."""

import asyncio
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from personal_asis.feishu import FeishuBridge


class Event:
    def __init__(self, text, platform="lark-fixture", sender="ou_owner", private=True):
        self.message_str, self.platform, self.sender, self.private = text, platform, sender, private
        self.stopped, self.call_llm = False, True
        self.message_obj = SimpleNamespace(message_id="message-1", raw_message=SimpleNamespace(message_type="text", parent_id=None))

    def get_platform_id(self): return self.platform
    def get_sender_id(self): return self.sender
    def is_private_chat(self): return self.private
    def should_call_llm(self, value): self.call_llm = value
    def stop_event(self): self.stopped = True


@unittest.skipUnless(importlib.util.find_spec("astrbot"), "run with the VPS AstrBot interpreter")
class AstrBotPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "integrations/astrbot_plugin_personal_asis/main.py"
        spec = importlib.util.spec_from_file_location("asis_plugin_smoke", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugin = self.module.PersonalAsis.__new__(self.module.PersonalAsis)
        self.plugin.bridge = FeishuBridge(Path(self.tmp.name))
        self.addCleanup(self.plugin.bridge.close)
        self.plugin.lock = asyncio.Lock()
        self.adapter = SimpleNamespace(meta=lambda: SimpleNamespace(name="lark"), connection_mode="socket")
        self.plugin.context = SimpleNamespace(get_platform_inst=lambda platform: self.adapter if platform == "lark-fixture" else None)
        self.sent = []
        async def send(*args):
            self.sent.append(args)
            return True
        self.plugin.send = send

    def bind(self):
        code = self.plugin.bridge.pairing("lark-fixture")["pairing_code"]
        self.plugin.bridge.bind("lark-fixture", "ou_owner", code)

    def test_unauthorized_other_platform_group_and_webhook_never_fall_through(self):
        for event in (Event("/asis search 芯片"), Event("/asis search 芯片", platform="qq"),
                      Event("/asis search 芯片", private=False)):
            asyncio.run(self.plugin.on_message(event))
            self.assertTrue(event.stopped)
            self.assertFalse(event.call_llm)
        self.bind()
        self.adapter.connection_mode = "webhook"
        event = Event("/asis search 芯片")
        asyncio.run(self.plugin.on_message(event))
        self.assertTrue(event.stopped)
        self.assertEqual(self.sent, [])

    def test_normal_message_is_unchanged_and_registered_regex_is_available(self):
        from astrbot.api.event import filter
        self.assertTrue(callable(filter.regex))
        event = Event("普通聊天")
        asyncio.run(self.plugin.on_message(event))
        self.assertFalse(event.stopped)
        self.assertTrue(event.call_llm)
        self.assertEqual(self.sent, [])

    def test_authorized_search_is_persisted_without_model_or_duplicate_send(self):
        self.bind()
        event = Event("/asis search 芯片")
        asyncio.run(self.plugin.on_message(event))
        self.assertTrue(event.stopped)
        self.assertFalse(event.call_llm)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("部分结果", self.sent[0][2])
        asyncio.run(self.plugin.on_message(event))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.plugin.bridge.db.execute("SELECT count(*) FROM routes").fetchone()[0], 1)

    def test_analysis_and_research_use_bound_owner_adapter_without_astrbot_model(self):
        self.bind()
        self.plugin.bridge.submit_analysis=Mock(return_value='synthetic-id')
        for command in ('/asis analyze 个人问题','/asis research 个人问题 | public chip query | https://example.com/article'):
            event=Event(command)
            asyncio.run(self.plugin.on_message(event))
            self.assertFalse(event.call_llm)
            self.assertTrue(event.stopped)
        args=self.plugin.bridge.submit_analysis.call_args.args
        self.assertEqual(args[3],'个人问题')
        self.assertEqual(args[4],{'public_query':'public chip query','urls':['https://example.com/article']})

    def test_analysis_status_keeps_delivered_state_after_relay_expires(self):
        self.bind()
        with self.plugin.bridge.db:
            self.plugin.bridge.db.execute('INSERT INTO analysis_routes VALUES(?,?,?,?,?)',('synthetic-id','lark-fixture','ou_owner','m',0))
            self.plugin.bridge.db.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',('delivery','synthetic-id','sent',0,0))
        asyncio.run(self.plugin.on_message(Event('/asis status synthetic-id')))
        self.assertIn('结果已回复此私聊',self.sent[0][2])


if __name__ == "__main__":
    unittest.main()

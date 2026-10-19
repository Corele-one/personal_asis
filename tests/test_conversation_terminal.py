import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import conversation as core, pa1
from personal_asis.pi_terminal import handle, main
from test_conversation import Provider, PI_AVAILABLE


class ConversationTerminalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home, 'synthetic-model', True, synthetic_only=False)

    def request(self, action, **data):
        return handle(self.home, {'engine':'conversation', 'action':action, **data})

    def test_default_native_entry_is_conversation_without_source_or_role(self):
        with patch('builtins.print') as output:
            self.assertEqual(main(['--home', str(self.home), '--check']), 0)
        value=json.loads(output.call_args.args[0])
        self.assertEqual(value['engine'], 'conversation')
        self.assertEqual(value['sources'], [])
        self.assertEqual(value['default_mode'], core.VERSION)
        self.assertEqual(value['model_generation_calls'], 0)

    def test_new_list_load_and_budget_use_session_core_without_work_store(self):
        thread=self.request('new')['thread']
        self.assertEqual(self.request('list')['chats'][0]['id'], thread)
        self.assertEqual(self.request('load', thread=thread)['mode'], core.VERSION)
        self.assertEqual(self.request('load', thread=thread)['messages'], [])
        self.assertIn('今日', self.request('budget', thread=thread)['text'])
        self.assertFalse((self.home/'work.sqlite3').exists())
        self.assertFalse((self.home/'terminal.sqlite3').exists())

    def test_scope_flags_are_legacy_opt_in(self):
        # Unknown synthetic source defaults are not invented for the new entry.
        with patch('builtins.print') as output:
            self.assertEqual(main(['--home', str(self.home), '--source','synthetic','--mode','research','--check']),0)
        self.assertEqual(json.loads(output.call_args.args[0])['engine'],'legacy')

    @unittest.skipUnless(PI_AVAILABLE,'actual Pi required')
    def test_native_adapter_multiturn_dedup_reload_and_forget(self):
        thread=self.request('new')['thread']
        provider=Provider(['缓存方向', '刚才说的是缓存方向'])
        real=core.send
        with patch.object(core,'send',lambda *a,**kw:real(*a,**kw,provider=provider)):
            first=self.request('run',thread=thread,query='讨论缓存',request_id='ui-turn-one')
            self.assertEqual(first['status'],'completed',first)
            self.assertEqual(first['usage'],{'total_tokens':50})
            duplicate=self.request('run',thread=thread,query='讨论缓存',request_id='ui-turn-one')
            self.assertTrue(duplicate['cached'])
            self.assertEqual(len(provider.calls),1)
            second=self.request('run',thread=thread,query='刚才哪个方向',request_id='ui-turn-two')
        self.assertEqual(second['status'],'completed',second)
        self.assertIn('讨论缓存',json.dumps(provider.calls[-1]['messages'],ensure_ascii=False))
        loaded=self.request('load',thread=thread)
        self.assertEqual(len(loaded['messages']),2)
        self.assertEqual(self.request('status',thread=thread)['request_id'],'ui-turn-two')
        self.request('forget',thread=thread)
        self.assertEqual(self.request('load',thread=thread)['messages'],[])
        self.assertEqual(core.budget_status(self.home)['daily_tokens'],100)

    @unittest.skipUnless(PI_AVAILABLE,'actual Pi required')
    def test_native_natural_tool_approval_shares_core_and_only_displays_new_charge(self):
        from test_conversation_tools import Web, action, supported
        thread=self.request('new')['thread']
        web=Web()
        provider=Provider([action('search_web',query='cache systems'),
                           action('fetch_web',url='https://example.com/research'),supported()])
        real=core.send
        def send(*args,**kwargs):
            return real(*args,**kwargs,provider=provider,services={'web':web,'resolver':lambda host:['8.8.8.8']})
        with patch.object(core,'send',send):
            first=self.request('run',thread=thread,query='请搜索公开资料',request_id='ui-search')
            self.assertEqual(first['status'],'waiting_permission')
            self.assertIn('cache systems',first['text'])
            self.assertEqual(first['usage']['total_tokens'],50)
            self.assertIn('回复“同意”',self.request('load',thread=thread)['messages'][0]['answer'])
            second=self.request('run',thread=thread,query='同意',request_id='ui-approve')
            self.assertEqual(second['status'],'completed',second)
            self.assertEqual(second['usage']['total_tokens'],100)
            repeated=self.request('run',thread=thread,query='同意',request_id='ui-approve')
            self.assertEqual(repeated['usage']['total_tokens'],0)
        self.assertEqual(len(web.calls),2)

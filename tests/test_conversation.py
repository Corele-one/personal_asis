import copy
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import conversation as c, pa1
from personal_asis.agent_model import ToolMiMo
from personal_asis.chat_cli import main as chat_main
from personal_asis.model_provider import ProviderUnknown
from personal_asis.runtime_adapter import PI_DIR

PI_AVAILABLE = bool(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir())


class Provider(ToolMiMo):
    def __init__(self, responses=None, hook=None):
        super().__init__('mac', 'synthetic-model')
        self.calls, self.responses, self.hook = [], responses or [], hook

    def credential(self):
        return 'SYNTHETIC_CREDENTIAL'

    def complete(self, payload, secret):
        self.calls.append(copy.deepcopy(payload))
        if self.hook:
            self.hook()
        value = self.responses.pop(0) if self.responses else '好的，我记得本会话讨论的缓存方向。'
        if isinstance(value, BaseException):
            raise value
        calls = None
        if value == 'tool':
            calls = [{'id': 'call-'+str(len(self.calls)), 'type': 'function', 'function': {
                'name': 'search_notes', 'arguments': '{"query":"cache"}'}}]
            content = None
        else:
            result = value if isinstance(value, dict) else {
                'status': 'conversational', 'answer': value, 'citations': [], 'uncertainty': ''}
            content = json.dumps(result, ensure_ascii=False)
        return {'content': content, 'tool_calls': calls, 'finish_reason': 'tool_calls' if calls else 'stop',
                'usage': {'prompt_tokens': 40, 'completion_tokens': 10, 'total_tokens': 50}}


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = pa1.fixture(self.tmp.name)
        pa1.configure(self.home, 'synthetic-model', True, synthetic_only=False)
        with c.ConversationStore(self.home) as store:
            self.sid = store.create()

    def test_unknown_protocol_is_not_silently_migrated(self):
        with c.ConversationStore(self.home) as store:
            with store.db:
                store.db.execute("UPDATE conversation_sessions SET version='future-v2'")
            with self.assertRaisesRegex(ValueError, 'protocol_changed'):
                store.session(self.sid)

    def test_concurrent_writer_is_rejected(self):
        with c.ConversationStore(self.home) as a, c.ConversationStore(self.home) as b:
            with a.lock(self.sid), self.assertRaisesRegex(ValueError, 'busy'):
                with b.lock(self.sid):
                    self.fail('must not get lock')

    def test_check_is_read_only_no_credential_or_model(self):
        output = []
        with patch.object(ToolMiMo, 'credential', side_effect=AssertionError('no credentials')):
            self.assertEqual(chat_main(self.home, check=True, output=output.append), 0)
        value = json.loads(output[0])
        self.assertEqual(value['model_calls'], 0)
        self.assertFalse(value['vps_or_astrbot_required'])
        self.assertFalse(value['streaming_text'])

    def test_credential_input_and_bad_ids_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid_message'):
            c.send(self.home, self.sid, 'api_key=sk-012345678901234567890123456789')
        with c.ConversationStore(self.home) as store:
            self.assertEqual(store.turns(self.sid), [])
            with self.assertRaisesRegex(ValueError, 'invalid_id'):
                store.session('../x')

    def test_persisted_progress_events_exclude_message_and_tool_bodies(self):
        with c.ConversationStore(self.home) as store:
            tid='event-turn'
            store.event(self.sid,tid,'turn_started')
            store.event(self.sid,tid,'tool_start',{'tool':'search_notes','query':'private body'})
            values=store.events(self.sid)
        self.assertEqual([v['kind'] for v in values],['turn_started','tool_start'])
        self.assertEqual(values[1]['payload'],{'tool':'search_notes'})
        self.assertNotIn('private body',json.dumps(values,ensure_ascii=False))


@unittest.skipUnless(PI_AVAILABLE, 'actual Pi and Node required')
class ConversationTests(StoreTests):
    def run_turn(self, question='你好', tid='t1', provider=None, **kwargs):
        return c.send(self.home, self.sid, question, turn_id=tid, provider=provider or Provider(), **kwargs)

    def test_three_turn_chat_has_native_history_and_no_retrieval_or_delegations(self):
        provider = Provider(['我们选择缓存一致性方向。', '它可以作为研究方向。', '刚才说的是缓存一致性。'])
        with patch.object(c, 'build_bundle', side_effect=AssertionError('no retrieval')):
            for i, question in enumerate(['研究方向选缓存一致性', '它适合做什么？', '刚才选了什么？']):
                value = self.run_turn(question, 't'+str(i), provider)
                self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(len(provider.calls), 3)
        messages = provider.calls[-1]['messages']
        self.assertEqual([m['role'] for m in messages], ['system', 'user', 'assistant', 'user', 'assistant', 'user'])
        self.assertIn('缓存一致性', messages[2]['content'])
        self.assertFalse((self.home/'work.sqlite3').exists())
        self.assertEqual(c.budget_status(self.home)['daily_tokens'], 150)
        self.assertEqual(value['result']['searches'], 0)
        self.assertTrue(all(p['response_format'] == {'type': 'json_object'} for p in provider.calls))
        self.assertNotIn('astrbot', json.dumps(provider.calls))

    def test_model_selected_personal_retrieval_and_refs(self):
        provider = Provider(['tool', {'status': 'supported', 'answer': '缓存失效 [E1]',
                                    'citations': ['E1'], 'uncertainty': '部分检索'}])
        events = []
        value = self.run_turn('从我的笔记查cache', provider=provider, on_event=events.append)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(value['result']['searches'], 1)
        self.assertEqual(value['result']['citations'], ['E1'])
        wire = json.dumps(provider.calls)
        for marker in ('PRIVATE_', 'UNAPPROVED_', str(self.home), 'file:'):
            self.assertNotIn(marker, wire)
        self.assertEqual([e['kind'] for e in events if e['phase'] == 'start'], ['model', 'tool', 'model'])

    def test_tool_failure_is_receipt_and_model_can_explain(self):
        provider = Provider(['tool', '本机检索暂不可用，请稍后再查。'])
        with patch.object(c, 'build_bundle', side_effect=OSError('PRIVATE_PATH_AND_BODY')):
            value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'completed', value)
        wire = json.dumps(provider.calls)
        self.assertIn('retrieval_unavailable', wire)
        self.assertNotIn('PRIVATE_PATH_AND_BODY', wire)

    def test_missing_evidence_can_abstain(self):
        provider = Provider(['tool', {'status': 'insufficient_evidence', 'answer': '', 'citations': [], 'uncertainty': ''}])
        with patch.object(c, 'build_bundle', side_effect=ValueError('no_current_provider_authorized_evidence')):
            value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(value['result']['status'], 'insufficient_evidence')

    def test_exit_reopen_and_same_turn_id_reuses_paid_result(self):
        first = self.run_turn('选择缓存方向')
        self.assertFalse(first['cached'])
        provider = Provider()
        duplicate = self.run_turn('选择缓存方向', provider=provider)
        self.assertTrue(duplicate['cached'])
        self.assertEqual(provider.calls, [])
        next_turn = self.run_turn('刚才选的哪个？', 't2', provider)
        self.assertEqual(next_turn['status'], 'completed', next_turn)
        self.assertEqual(next_turn['session_id'], first['session_id'])
        self.assertNotEqual(next_turn['run_id'], first['run_id'])
        self.assertIn('选择缓存方向', json.dumps(provider.calls, ensure_ascii=False))
        with self.assertRaisesRegex(ValueError, 'conflict'):
            self.run_turn('改了内容')

    def test_checkpoint_resume_replays_wire_order_without_duplicate_model(self):
        first = Provider(['tool'])
        interrupted = self.run_turn(provider=first, step_limit=1)
        self.assertEqual(interrupted['status'], 'interrupted')
        final = Provider([{'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        value = c.send(self.home, self.sid, turn_id='t1', resume=True, provider=final)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(len(first.calls), 1)
        self.assertEqual(len(final.calls), 1)
        self.assertEqual(c.budget_status(self.home)['daily_tokens'], 100)
        # Checkpoint after a tool must preserve the original tool JSON field order too.
        two = Provider(['tool'])
        self.run_turn('cache', 't2', two, step_limit=2)
        provider = Provider([{'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        final = c.send(self.home, self.sid, turn_id='t2', resume=True, provider=provider)
        self.assertEqual(final['status'], 'completed', final)
        self.assertEqual(len(provider.calls), 1)

    def test_unknown_paid_call_cannot_resume_or_repeat(self):
        provider = Provider([ProviderUnknown('private timeout body')])
        value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['error'], 'chat_model_result_unknown_no_retry')
        with self.assertRaisesRegex(ValueError, 'requires_explicit_resume_or_is_failed'):
            c.send(self.home, self.sid, turn_id='t1', resume=True, provider=Provider())
        self.assertEqual(c.budget_status(self.home)['unresolved_calls'], 1)
        with self.assertRaises(ValueError):
            self.run_turn(provider=Provider())

    def test_crash_after_billing_before_commit_is_not_paid_again(self):
        original = c.ConversationHost.commit
        def crash(host, key, args, output):
            if key.startswith('model:'):
                raise KeyboardInterrupt()
            return original(host, key, args, output)
        with patch.object(c.ConversationHost, 'commit', crash):
            value = self.run_turn()
        self.assertEqual(value['status'], 'interrupted')
        provider = Provider()
        value = c.send(self.home, self.sid, turn_id='t1', resume=True, provider=provider)
        self.assertEqual(value['status'], 'failed')
        self.assertIn('no_retry', value['error'])
        self.assertEqual(provider.calls, [])
        self.assertEqual(c.budget_status(self.home)['daily_tokens'], 50)

    def test_revocation_invalidates_evidence_and_transitive_history_and_purges(self):
        provider = Provider(['tool', {'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        self.assertEqual(self.run_turn(provider=provider)['status'], 'completed')
        self.run_turn('解释它', 't2')
        self.run_turn('再说一下', 't3')
        path = self.home/'sources.yaml'
        config = json.loads(path.read_text())
        config['sources'][0]['model_providers'] = []
        path.write_text(json.dumps(config))
        self.assertEqual(c.inspect(self.home, self.sid)['status'], 'invalidated')
        with c.ConversationStore(self.home) as store:
            self.assertTrue(all(r['state'] is None and r['result'] is None for r in store.turns(self.sid)))
        with self.assertRaisesRegex(ValueError, 'no_retry'):
            self.run_turn(provider=Provider())
        provider = Provider()
        self.assertEqual(self.run_turn('你好', 'fresh', provider)['status'], 'completed')
        self.assertEqual(len(provider.calls[0]['messages']), 2)

    def test_changed_document_invalidates_prior_answers(self):
        provider = Provider(['tool', {'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        self.run_turn(provider=provider)
        (self.home/'source/cache.md').write_text('# Changed\nnew cache\n')
        self.assertEqual(c.inspect(self.home, self.sid)['status'], 'invalidated')

    def test_retention_forget_keep_tombstones_no_retry(self):
        self.run_turn()
        with c.ConversationStore(self.home) as store, store.db:
            store.db.execute('UPDATE conversation_turns SET at=0')
        self.assertEqual(c.inspect(self.home, self.sid)['status'], 'expired')
        with self.assertRaisesRegex(ValueError, 'no_retry'):
            self.run_turn()
        self.run_turn('你好', 't2')
        with c.ConversationStore(self.home) as store:
            store.forget(self.sid)
        self.assertEqual(c.inspect(self.home, self.sid)['status'], 'forgotten')
        self.assertEqual(c.budget_status(self.home)['daily_tokens'], 100)

    def test_history_is_bounded_and_citations_not_carried_as_current_evidence(self):
        provider = Provider(['回答'+str(i)+'x'*80 for i in range(8)])
        for i in range(8):
            value = self.run_turn('问题'+str(i), 't'+str(i), provider)
            self.assertEqual(value['status'], 'completed', value)
        self.assertLessEqual(len(provider.calls[-1]['messages']), 10)
        self.assertTrue(value['result']['history_truncated'])
        for payload in provider.calls:
            self.assertLessEqual(len(c.dumps({'messages': payload['messages'], 'tools': payload.get('tools', [])}).encode()), 8192)

    def test_budget_exhaustion_prevents_call(self):
        path = self.home/'pa1.json'
        data = json.loads(path.read_text())
        data.update(daily_tokens=100, monthly_tokens=100)
        path.write_text(json.dumps(data))
        provider = Provider()
        value = self.run_turn(provider=provider)
        self.assertEqual(value['error'], 'model_budget_exhausted')
        self.assertEqual(provider.calls, [])

    def test_cli_chat_resume_history_and_quit_uses_same_core(self):
        lines = iter(['选择cache', '它呢', '/history', '/budget', '/quit'])
        output = []
        provider = Provider()
        real_send = c.send
        def send(*args, **kwargs):
            return real_send(*args, **kwargs, provider=provider)
        with patch.object(c, 'send', send):
            self.assertEqual(chat_main(self.home, session=self.sid, input_fn=lambda _: next(lines), output=output.append), 0)
        self.assertEqual(len(provider.calls), 2)
        self.assertIn('选择cache', '\n'.join(output))
        self.assertIn('恢复：', output[-1])

    def test_synthetic_only_does_not_read_personal_notes(self):
        pa1.configure(self.home, synthetic_only=True)
        provider = Provider(['tool', '当前资料工具被限制，无法检索个人笔记。'])
        with patch.object(c, 'build_bundle', side_effect=AssertionError('must not read')):
            value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'completed', value)
        self.assertIn('real_source_tools_disabled', json.dumps(provider.calls))

    def test_cancel_interrupted_turn_allows_new_turn_without_resuming_it(self):
        self.run_turn(step_limit=1)
        with self.assertRaisesRegex(ValueError, 'previous_turn_unfinished'):
            self.run_turn('下一条', 't2')
        c.cancel(self.home, self.sid, 't1')
        self.assertEqual(c.inspect(self.home, self.sid)['status'], 'cancelled')
        self.assertEqual(self.run_turn('下一条', 't2')['status'], 'completed')
        with self.assertRaises(ValueError):
            c.send(self.home, self.sid, turn_id='t1', resume=True, provider=Provider())

    def test_turn_id_cannot_be_reused_in_another_session(self):
        self.run_turn()
        with c.ConversationStore(self.home) as store:
            other = store.create()
        with self.assertRaisesRegex(ValueError, 'turn_id_conflict'):
            c.send(self.home, other, '你好', turn_id='t1', provider=Provider())

    def test_search_bound_forces_final_response(self):
        provider = Provider(['tool', 'tool', '缺少更多证据，暂时无法继续。'])
        value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(value['result']['searches'], 2)
        self.assertNotIn('tools', provider.calls[-1])

    def test_checkpoint_at_search_bound_preserves_earlier_payloads(self):
        provider = Provider(['tool', 'tool'])
        value = self.run_turn(provider=provider, step_limit=4)
        self.assertEqual(value['status'], 'interrupted', value)
        final = Provider(['检索已达到本轮上限。'])
        value = c.send(self.home, self.sid, turn_id='t1', resume=True, provider=final)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(len(final.calls), 1)
        self.assertNotIn('tools', final.calls[0])

    def test_json_tool_action_is_normalized_to_same_checked_pi_call(self):
        provider = Provider([{'tool': 'search_notes', 'arguments': {'query': 'cache'}},
                             {'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'completed', value)
        self.assertEqual(value['result']['searches'], 1)
        self.assertEqual(provider.calls[-1]['messages'][-1]['role'], 'user')
        self.assertIn('本机工具结果', provider.calls[-1]['messages'][-1]['content'])
        self.assertTrue(all('tools' not in p for p in provider.calls))

    def test_unknown_json_action_cannot_escape_tool_allowlist(self):
        provider = Provider([{'tool': 'bash', 'arguments': {'query': 'secret'}}])
        with patch.object(c, 'build_bundle', side_effect=AssertionError('never called')):
            value = self.run_turn(provider=provider)
        self.assertEqual(value['status'], 'failed')
        self.assertEqual(value['error'], 'chat_invalid_model_tool_action')

    def test_revocation_during_paid_response_does_not_restore_purged_content(self):
        first = Provider(['tool'])
        self.run_turn(provider=first, step_limit=2)
        def revoke():
            path = self.home/'sources.yaml'
            data = json.loads(path.read_text())
            data['sources'][0]['model_providers'] = []
            path.write_text(json.dumps(data))
        provider = Provider(hook=revoke)
        value = c.send(self.home, self.sid, turn_id='t1', resume=True, provider=provider)
        self.assertEqual(value['status'], 'invalidated')
        with c.ConversationStore(self.home) as store:
            self.assertIsNone(store.get(self.sid, 't1')['state'])

    def test_existing_maintenance_cleans_conversation_on_source_revocation(self):
        from personal_asis.pa1_maintenance import clean
        provider = Provider(['tool', {'status': 'supported', 'answer': 'cache [E1]', 'citations': ['E1'], 'uncertainty': ''}])
        self.run_turn(provider=provider)
        path = self.home/'sources.yaml'
        config = json.loads(path.read_text())
        config['sources'][0]['model_providers'] = []
        path.write_text(json.dumps(config))
        report = clean(self.home)
        self.assertEqual(report['conversation_turns_invalidated'], 1)

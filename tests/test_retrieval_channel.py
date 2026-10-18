import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.agent_channel import AgentRelay, AgentWorker
from personal_asis.coordinator import ProtocolError
from personal_asis.evidence import control_server
from personal_asis.feishu import FeishuBridge, summary
from personal_asis.retrieval_eval import fixture
from personal_asis.retrieval_channel import snapshot
from test_analysis_channel import CRYPTO


@unittest.skipUnless(CRYPTO, 'encrypted reader dependency required')
class RetrievalChannelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        fixture(self.home)
        self.policy(remote=True)
        self.bridge = FeishuBridge(self.home)
        self.addCleanup(self.bridge.close)
        code = self.bridge.pairing('lark')['pairing_code']
        self.assertTrue(self.bridge.bind('lark', 'ou_owner', code))
        self.relay = AgentRelay()
        server, path = control_server(self.home, self.relay, 'agent.sock')
        self.addCleanup(path.unlink, missing_ok=True)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

    def policy(self, remote):
        path = self.home / 'sources.yaml'
        data = json.loads(path.read_text())
        data['sources'][0].update(remote_metadata=remote, remote_evidence=remote)
        path.write_text(json.dumps(data))

    def submit(self, message='one', query='缓存一致性', sources=None):
        return self.bridge.agent.submit('lark', 'ou_owner', message, 'retrieve',
                                        query=query, source_ids=sources or ['notes'])

    def worker(self):
        relay = self.relay
        class Client:
            def authenticated(self, path, data):
                if path == '/v1/agent/poll':
                    return relay.poll('mac', data['policy_hash'], data['busy'])
                if path == '/v1/agent/complete':
                    return relay.complete('mac', data)
                raise AssertionError('unexpected_transport')
        return AgentWorker(self.home, client=Client(), executor=lambda *a, **k: self.fail('no Agent/model execution'))

    def test_encrypted_readonly_roundtrip_and_no_work_or_model_ledger(self):
        receipt = self.submit()
        self.assertTrue(receipt['submitted'])
        with patch('personal_asis.model_provider.MiMo.complete', side_effect=AssertionError('no model')):
            self.worker().once()
        rows = self.bridge.agent.pending()
        self.assertEqual(len(rows), 1)
        value = rows[0][1]['result']
        self.assertEqual(value['kind'], 'retrieval_v2')
        self.assertEqual(value['model_calls'], 0)
        self.assertTrue(value['evidence'])
        self.assertNotIn(str(self.home), json.dumps(value))
        text = summary(rows[0][1])
        self.assertIn('未调用模型', text)
        self.assertIn('候选原文', text)
        self.assertIn('缓存一致性协议', text)
        self.assertFalse((self.home / 'pa1.sqlite3').exists())
        self.assertFalse((self.home / 'work.sqlite3').exists())
        self.assertNotIn('缓存一致性'.encode(), (self.home / 'feishu.sqlite3').read_bytes())

    def test_schema_filters_query_channel_and_rejects_mode_or_implicit_sources(self):
        self.submit()
        job = next(iter(self.relay.jobs.values()))
        request = {k: job[k] for k in ('request_id', 'target_id', 'action', 'query', 'source_ids', 'channel', 'client_nonce', 'public_key')}
        for change in [{'query': 'Authorization: Bearer SYNTHETIC_SECRET'}, {'query': ''},
                       {'source_ids': None}, {'mode': 'research'}, {'channel': 'pwa'}]:
            with self.assertRaises(ProtocolError):
                AgentRelay().request({**request, **change})

    def test_remote_permission_revoked_before_execution_returns_safe_error(self):
        self.submit()
        self.policy(remote=False)
        self.worker().once()
        value = self.bridge.agent.pending()[0][1]['result']
        self.assertEqual(value['kind'], 'retrieval_v2')
        self.assertIn('error', value)
        self.assertNotIn('evidence', value)
        self.assertNotIn('缓存一致性协议', summary({'kind': 'agent', 'target_id': 'x', 'result': value}))

    def test_unknown_or_provider_denied_source_does_not_leak(self):
        self.submit(query='互连延迟', sources=['reading_folo'])
        self.worker().once()
        value = self.bridge.agent.pending()[0][1]['result']
        self.assertIn('error', value)
        self.assertNotIn('evidence', value)
        with self.assertRaises(ValueError):
            snapshot(self.home, {'query': '缓存', 'source_ids': ['unknown'], 'channel': 'feishu'})

    def test_same_message_dedup_and_unknown_send_never_repeats(self):
        first = self.submit()
        second = self.submit()
        self.assertTrue(second['duplicate'])
        self.assertEqual(first['target_id'], second['target_id'])
        self.worker().once()
        row = self.bridge.agent.pending()[0]
        sent = []
        async def send(*args):
            sent.append(args)
            raise TimeoutError()
        self.assertEqual(asyncio.run(self.bridge.deliver(*row, send)), 'unknown')
        asyncio.run(self.bridge.deliver(*row, send))
        self.assertEqual(len(sent), 1)

    def test_policy_stamp_change_invalidates_pending_ciphertext(self):
        self.submit()
        worker = self.worker()
        worker.once()
        row = self.bridge.agent.pending()[0]
        self.policy(remote=False)
        self.relay.poll('mac', worker.stamp())
        async def send(*args):
            self.fail('revoked evidence must not be sent')
        self.assertEqual(asyncio.run(self.bridge.deliver(*row, send)), 'revoked_or_expired')

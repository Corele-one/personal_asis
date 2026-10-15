import asyncio
import base64
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from personal_asis.agent_channel import AgentRelay, aad
from personal_asis.coordinator import ProtocolError
from personal_asis.evidence import encrypt, control_server
from personal_asis.feishu import FeishuBridge, summary
from test_analysis_channel import CRYPTO


@unittest.skipUnless(CRYPTO,'encrypted reader dependency required')
class AgentFeishuTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        self.bridge=FeishuBridge(self.home);self.addCleanup(self.bridge.close)
        self.relay=AgentRelay()
        server,path=control_server(self.home,self.relay,'agent.sock')
        self.addCleanup(path.unlink,missing_ok=True);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        code=self.bridge.pairing('lark')['pairing_code'];self.bridge.bind('lark','ou_owner',code)

    def submit(self, message='m', action='run', **kw):
        if action=='run':kw.update(query='SYNTHETIC_QUESTION_cache',source_ids=['study'])
        return self.bridge.agent.submit('lark','ou_owner',message,action,**kw)

    def complete(self, value):
        job=self.relay.poll('mac','a'*64)['job']
        self.relay.complete('mac',{'request_id':job['request_id'],'lease':job['lease'],'status':'ready',
            'envelope':encrypt(value,job,aad(job))})
        return job

    def test_bound_owner_dedup_scope_and_no_durable_body_or_key(self):
        with self.assertRaises(ProtocolError):
            self.bridge.agent.submit('lark','ou_other','m','run',query='cache',source_ids=['study'])
        first=self.submit();repeated=self.submit()
        self.assertEqual(first['request_id'],repeated['request_id'])
        self.assertTrue(repeated['duplicate'])
        self.assertEqual(len(self.relay.jobs),1)
        with self.assertRaises(ProtocolError):
            self.bridge.agent.submit('lark','ou_owner','m','run',query='changed',source_ids=['study'])
        private=self.bridge.agent.keys[first['request_id']][0]
        self.assertNotIn(b'SYNTHETIC_QUESTION',b''.join(p.read_bytes() for p in self.home.glob('*.sqlite3*')))
        self.assertEqual(private.key_size,2048)

    def test_role_mode_identity_roundtrip_and_cannot_change_paid_work(self):
        self.submit(mode='career')
        job=self.relay.poll('mac','a'*64)['job']
        self.assertEqual(job['mode'],'career')
        self.assertEqual(job['source_ids'],['study'])
        self.assertTrue(self.submit(mode='career')['duplicate'])
        with self.assertRaises(ProtocolError):self.submit(mode='life')
        with self.assertRaises(ProtocolError):self.submit('bad-mode',mode='shell')

    def test_deferred_card_transport_has_no_early_delivery_or_implicit_retry_and_expires_keys(self):
        receipt=self.bridge.agent.submit('lark','ou_owner','card-command','run',
            query='SYNTHETIC_CARD_INPUT',source_ids=['study'],mode='research',
            reply_message_id='om_card',defer_transport=True)
        self.assertEqual(self.relay.jobs,{})
        self.assertEqual(self.bridge.agent.pending(),[])
        self.assertIn('transport_payload',receipt)
        repeated=self.bridge.agent.submit('lark','ou_owner','card-command','run',
            query='SYNTHETIC_CARD_INPUT',source_ids=['study'],mode='research',
            reply_message_id='om_card',defer_transport=True)
        self.assertTrue(repeated['duplicate'])
        self.assertNotIn('transport_payload',repeated)
        before=self.bridge.clock();self.bridge.clock=lambda:before+901
        self.assertEqual(self.bridge.agent.pending(),[])
        self.assertNotIn(receipt['request_id'],self.bridge.agent.keys)

    def test_control_has_original_target_and_cannot_change_question_or_scope(self):
        target=str(uuid.uuid4())
        self.submit('control','pause',target_id=target)
        job=self.relay.poll('mac','a'*64)['job']
        self.assertEqual(job['target_id'],target)
        self.assertEqual(job['channel'],'feishu')
        with self.assertRaises(ProtocolError):
            self.bridge.agent.submit('lark','ou_owner','bad','resume',target_id=target,query='changed')

    def test_encrypted_result_delivery_unknown_and_restart_do_not_resend(self):
        receipt=self.submit()
        value={'target_id':receipt['target_id'],'state':'completed','delegation_state':'active',
            'committed_actions':2,'unresolved_executions':0,'usage':None,
            'result':{'answer':'SYNTHETIC_PRIVATE_ANSWER [E1]','uncertainty':'partial','citations':['E1'],
                'evidence':[{'id':'E1','title':'Synthetic','source_id':'study','path_hint':'cache.md',
                    'line_start':2,'excerpt':'SYNTHETIC_PRIVATE_EXCERPT'}]}}
        self.complete(value)
        rows=self.bridge.agent.pending();self.assertEqual(len(rows),1)
        sent=[]
        async def send(*args):sent.append(args);raise TimeoutError()
        self.assertEqual(asyncio.run(self.bridge.deliver(*rows[0],send)),'unknown')
        asyncio.run(self.bridge.deliver(*rows[0],send))
        self.assertEqual(len(sent),1)
        self.assertIn('SYNTHETIC_PRIVATE_ANSWER',sent[0][2])
        self.assertNotIn(b'SYNTHETIC_PRIVATE',b''.join(p.read_bytes() for p in self.home.glob('*.sqlite3*')))
        restarted=FeishuBridge(self.home);self.addCleanup(restarted.close)
        duplicate=restarted.agent.submit('lark','ou_owner','m','run',query='SYNTHETIC_QUESTION_cache',source_ids=['study'])
        self.assertTrue(duplicate['duplicate'])
        self.assertEqual(restarted.agent.pending(),[])

    def test_rebinding_and_ready_ciphertext_revocation_block_delivery(self):
        self.submit();self.complete({'error':'agent_request_not_found'})
        row=self.bridge.agent.pending()[0]
        self.relay.poll('mac','b'*64)
        async def fail(*args):self.fail('revoked ciphertext must never be sent')
        self.assertEqual(asyncio.run(self.bridge.deliver(*row,fail)),'revoked_or_expired')
        code=self.bridge.pairing('lark')['pairing_code'];self.bridge.bind('lark','ou_new',code)
        self.assertFalse(self.bridge.agent.keys)
        self.assertEqual(self.bridge.db.execute('SELECT count(*) FROM agent_routes').fetchone()[0],0)

    def test_socket_unknown_submission_keeps_receipt_and_never_reissues_on_duplicate(self):
        with patch('personal_asis.agent_feishu.relay_control',side_effect=TimeoutError()) as control:
            with self.assertRaises(TimeoutError):self.submit()
            duplicate=self.submit()
            self.assertFalse(duplicate['submitted'])
            self.assertEqual(control.call_count,1)

    def test_private_snapshot_summary_excludes_unreferenced_evidence(self):
        view={'kind':'agent','target_id':'synthetic','result':{'state':'paused','delegation_state':'paused',
            'committed_actions':2,'unresolved_executions':1}}
        text=summary(view)
        self.assertIn('已暂停',text)
        self.assertIn('本机核对',text)
        self.assertIn('不会重做未知调用',text)

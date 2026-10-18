import base64
import json
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
import uuid

from personal_asis.agent_channel import AgentRelay, AgentWorker, aad
from personal_asis.coordinator import ProtocolError
from personal_asis.evidence import encrypt
from personal_asis import pa1
from personal_asis.agent import execute
from personal_asis.runtime_adapter import PI_DIR
from personal_asis.work import WorkStore
from test_analysis_channel import CRYPTO
from test_agent import FakeTools


@unittest.skipUnless(CRYPTO,'encrypted reader dependency required')
class AgentRelayTests(unittest.TestCase):
    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        self.now=0
        self.relay=AgentRelay(clock=lambda:self.now)
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=self.key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.data={'request_id':str(uuid.uuid4()),'target_id':str(uuid.uuid4()),'action':'run',
            'query':'cache','source_ids':['synthetic'],'channel':'pwa',
            'client_nonce':base64.b64encode(b'x'*16).decode(),'public_key':base64.b64encode(public).decode()}

    def decrypt(self, job):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        envelope=self.relay.get(job['request_id'])['envelope']
        raw=self.key.decrypt(base64.b64decode(envelope['wrapped_key']),padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        return json.loads(AESGCM(raw).decrypt(base64.b64decode(envelope['nonce']),
            base64.b64decode(envelope['ciphertext']),aad(job)))

    def command(self, action):
        return {**self.data,'request_id':str(uuid.uuid4()),'action':action,'query':None,'source_ids':None}

    def test_identity_scope_rejects_credentials_and_control_scope_changes(self):
        self.relay.request(self.data);self.relay.request(self.data)
        for change in ({'query':'changed'},{'source_ids':[]},{'target_id':'bad'},
                       {'channel':'feishu'},{'query':'api_key: sk-'+('x'*30)},
                       {'action':'resume'},{'request_id':str(uuid.uuid4()),'action':'shell'}):
            with self.assertRaises(ProtocolError):
                self.relay.request({**self.data,**change})

    def test_new_web_options_are_explicit_frozen_and_not_valid_on_controls(self):
        data={**self.data,'web':True,'public_queries':['SQLite WAL official documentation'],'source_ids':['public_web']}
        self.relay.request(data)
        job=self.relay.poll('mac','a'*64)['job']
        self.assertTrue(job['web']);self.assertEqual(job['public_queries'],data['public_queries'])
        for change in ({'web':False},{'public_queries':['我的私密日记']},{'mode':'research'},
                       {'action':'resume','query':None,'source_ids':None}):
            with self.assertRaises(ProtocolError):AgentRelay().request({**data,**change})

    def test_busy_node_accepts_controls_but_not_second_run_and_only_mac(self):
        self.relay.request(self.data)
        self.assertIsNone(self.relay.poll('rog','a'*64)['job'])
        first=self.relay.poll('mac','a'*64)['job']
        other={**self.data,'request_id':str(uuid.uuid4()),'target_id':str(uuid.uuid4())}
        self.relay.request(other)
        pause=self.command('pause');self.relay.request(pause)
        self.assertEqual(self.relay.poll('mac','a'*64,True)['job']['action'],'pause')
        self.assertIsNone(self.relay.poll('mac','a'*64,True)['job'])
        self.assertEqual(first['target_id'],self.data['target_id'])

    def test_ciphertext_context_lease_expiry_and_policy_invalidation(self):
        self.relay.request(self.data)
        job=self.relay.poll('mac','a'*64)['job']
        reply={'request_id':job['request_id'],'lease':job['lease'],'status':'ready',
               'envelope':encrypt({'answer':'SYNTHETIC_PRIVATE'},job,aad(job))}
        with self.assertRaises(ProtocolError):self.relay.complete('rog',reply)
        self.relay.complete('mac',reply)
        self.assertNotIn('SYNTHETIC_PRIVATE',json.dumps(self.relay.get(job['request_id'])))
        self.assertEqual(self.decrypt(job)['answer'],'SYNTHETIC_PRIVATE')
        self.relay.poll('mac','b'*64)
        self.assertEqual(self.relay.get(job['request_id'])['status'],'revoked')
        self.now=31
        with self.assertRaises(ProtocolError):self.relay.get(job['request_id'])

    def test_fresh_completion_revokes_prior_ciphertext_but_retains_own_receipt(self):
        self.relay.request(self.data)
        first=self.relay.poll('mac','a'*64)['job']
        self.relay.complete('mac',{'request_id':first['request_id'],'lease':first['lease'],
            'status':'ready','envelope':encrypt({'error':'old'},first,aad(first)),'policy_hash':'a'*64})
        control=self.command('pause');self.relay.request(control)
        second=self.relay.poll('mac','a'*64)['job']
        data={'request_id':second['request_id'],'lease':second['lease'],'status':'ready',
              'envelope':encrypt({'error':'fresh'},second,aad(second)),'policy_hash':'b'*64}
        for change in ({'lease':'wrong'},{'policy_hash':'invalid'}):
            with self.assertRaises(ProtocolError):self.relay.complete('mac',{**data,**change})
            self.assertEqual(self.relay.get(first['request_id'])['status'],'ready')
        self.relay.complete('mac',data)
        self.assertEqual(self.relay.get(first['request_id'])['status'],'revoked')
        self.assertEqual(self.relay.get(second['request_id'])['status'],'ready')
        self.relay.poll('mac','b'*64)
        self.assertEqual(self.relay.get(second['request_id'])['status'],'ready')


@unittest.skipUnless(CRYPTO and shutil.which('node') and
    (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir(),'optional Pi and crypto required')
class AgentChannelTests(unittest.TestCase):
    decrypt=AgentRelayTests.decrypt
    command=AgentRelayTests.command
    def setUp(self):
        AgentRelayTests.setUp(self)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        pa1.configure(self.home,'synthetic-model',True,synthetic_only=False)
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0].update(remote_metadata=True,remote_evidence=True)
        (self.home/'sources.yaml').write_text(json.dumps(data))
        self.provider=FakeTools()
        relay=self.relay
        class Client:
            def authenticated(client,route,data):
                if route.endswith('/poll'):
                    return relay.poll('mac',data['policy_hash'],data['busy'])
                return relay.complete('mac',data)
        self.worker=AgentWorker(self.home,Client(),lambda *args,**kw:execute(*args,provider=self.provider,**kw))

    def drain(self, job):
        for _ in range(300):
            self.worker.once()
            if self.relay.get(job['request_id'])['status']=='ready':
                return self.decrypt(job)
            time.sleep(.01)
        self.fail('synthetic foreground run failed to complete')

    def send(self, job):
        self.relay.request(job)
        return self.drain(job)

    def test_real_pi_encrypted_result_and_restart_replay_without_paid_repeat(self):
        first=self.send(self.data)
        self.assertEqual(first['state'],'completed')
        self.assertEqual(first['result']['citations'],['E1','E2'])
        self.assertNotIn('original_uri',first['result']['evidence'][0])
        self.assertNotIn('actions',first)
        self.assertEqual(len(self.provider.calls),2)
        self.relay.jobs.clear()
        repeated=self.send(self.data)
        self.assertEqual(repeated['state'],'completed')
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(self.send(self.command('status'))['state'],'completed')
        self.assertEqual(len(self.provider.calls),2)

    def test_explicit_public_web_encrypted_path_has_no_local_bootstrap(self):
        from test_agent_web import ScriptedModel,FakeWeb,PUBLIC,URL
        self.provider=ScriptedModel([],['E1'])
        backend=FakeWeb()
        self.worker.executor=lambda *args,**kw:execute(*args,provider=self.provider,web_provider=backend,**kw)
        data={**self.data,'source_ids':['public_web'],'web':True,'public_queries':[PUBLIC],
              'query':'公开缓存一致性资料'}
        result=self.send(data)
        self.assertEqual(result['state'],'completed')
        self.assertEqual(result['result']['evidence'][0]['kind'],'public_web')
        self.assertEqual(result['result']['evidence'][0]['url'],URL)
        self.assertEqual(result['result']['web_usage']['local_searches'],0)

    def test_domain_update_and_payload_cleanup_revoke_ready_ciphertext_on_next_poll(self):
        from personal_asis.domain_context import DomainContexts
        self.send(self.data)
        before=self.worker.stamp()
        with DomainContexts(self.home) as contexts:
            contexts.set('research','SYNTHETIC_GOAL','',['synthetic'],'one',allow_model=True)
        self.assertNotEqual(before,self.worker.stamp())
        self.worker.once()
        self.assertEqual(self.relay.get(self.data['request_id'])['status'],'revoked')
        current=self.send(self.command('status'))
        self.assertEqual(current['state'],'completed')
        before=self.worker.stamp()
        with WorkStore(self.home/'work.sqlite3') as work:
            did=work.db.execute('SELECT id FROM delegations WHERE request_id=?',('agent:'+self.data['target_id'],)).fetchone()[0]
            work.clean(did)
        self.assertNotEqual(before,self.worker.stamp())
        self.worker.once()
        self.assertTrue(all(v['status']!='ready' for v in self.relay.jobs.values()))

    def test_pause_is_responsive_during_model_and_unknown_never_retried(self):
        entered,release=threading.Event(),threading.Event()
        def block():
            entered.set();release.wait(5)
        self.provider=FakeTools(hook=block)
        self.relay.request(self.data);self.worker.once()
        self.assertTrue(entered.wait(2))
        paused=self.send(self.command('pause'))
        self.assertEqual(paused['state'],'paused')
        self.assertEqual(paused['unresolved_executions'],1)
        release.set()
        self.drain(self.data)
        resumed=self.send(self.command('resume'))
        self.assertEqual(resumed['unresolved_executions'],1)
        self.assertEqual(len(self.provider.calls),1)

    def test_cancel_blocks_recovery_and_old_resume_receipt_cannot_reopen_pause(self):
        self.provider=FakeTools(behavior='unknown')
        self.send(self.data)
        resume=self.command('resume')
        self.send(resume)
        self.send(self.command('pause'))
        self.relay.jobs.clear()
        self.assertEqual(self.send(resume)['state'],'paused')
        self.assertEqual(self.send(self.command('cancel'))['state'],'cancelled')
        self.assertEqual(self.send(self.command('resume'))['state'],'cancelled')
        self.assertEqual(len(self.provider.calls),1)

    def test_channel_permission_refused_before_evidence_can_reach_next_model(self):
        data=json.loads((self.home/'sources.yaml').read_text())
        data['sources'][0]['remote_evidence']=False
        (self.home/'sources.yaml').write_text(json.dumps(data))
        value=self.send(self.data)
        self.assertIn('channel_permission_denied',value['error'])
        self.assertEqual(len(self.provider.calls),0)
        self.assertFalse(any(m['role']=='tool' for call in self.provider.calls for m in call['messages']))

    def test_bad_recipient_key_has_no_local_receipt_or_paid_call(self):
        data={**self.data,'public_key':base64.b64encode(b'not-a-key'*30).decode()}
        self.relay.request(data);self.worker.once()
        self.assertEqual(self.relay.get(data['request_id'])['status'],'failed')
        self.assertFalse((self.home/'work.sqlite3').exists())
        self.assertEqual(len(self.provider.calls),0)

    def test_fresh_status_cannot_disclose_revoked_or_changed_evidence(self):
        self.send(self.data)
        (self.home/'source/cache.md').write_text('changed')
        value=self.send(self.command('status'))
        self.assertIn('error',value)
        self.assertNotIn('result',value)
        self.assertEqual(len(self.provider.calls),2)

    def test_committed_checkpoint_pauses_then_resumes_in_new_worker_without_repeat(self):
        self.worker.executor=lambda *a,**kw:execute(*a,provider=self.provider,
            step_limit=None if kw.get('resume') else 2,**kw)
        first=self.send(self.data)
        self.assertEqual(first['committed_actions'],2)
        self.assertEqual(self.send(self.command('pause'))['state'],'paused')
        self.worker=AgentWorker(self.home,self.worker.client,
            lambda *a,**kw:execute(*a,provider=self.provider,**kw))
        final=self.send(self.command('resume'))
        self.assertEqual(final['state'],'completed')
        self.assertEqual(final['result']['usage']['total_tokens'],180)
        self.assertEqual(len(self.provider.calls),2)

    def test_expired_foreground_request_does_not_start_paid_call(self):
        self.relay.request(self.data)
        self.now=899
        value=self.drain(self.data)
        self.assertEqual(value['error'],'agent_channel_request_expired')
        self.assertEqual(len(self.provider.calls),0)

    def test_role_mode_roundtrip_paid_replay_cross_channel_and_control_scope(self):
        from test_agent_roles import RolesProvider
        self.provider=RolesProvider()
        job={**self.data,'mode':'team'}
        value=self.send(job)
        self.assertEqual(value['state'],'completed')
        self.assertEqual(len(value['roles']),3)
        self.assertEqual(value['role_plan']['mode'],'team')
        self.assertEqual(value['result']['specialist_calls'],3)
        self.assertNotIn('original_uri',json.dumps(value))
        resumed=self.send({**self.command('resume'),'channel':'feishu'})
        self.assertEqual(resumed['state'],'completed')
        self.assertEqual(len(self.provider.calls),4)
        with self.assertRaises(ProtocolError):
            self.relay.request({**self.command('resume'),'mode':'life'})
        with self.assertRaises(ProtocolError):
            self.relay.request({**job,'request_id':str(uuid.uuid4()),'mode':'shell'})

    def test_host_initial_search_permits_direct_answer_and_counts_against_bound(self):
        class Direct(FakeTools):
            def complete(provider,payload,secret):
                provider.calls.append(payload)
                self.assertIn('本机已先执行一次 search_notes',payload['messages'][1]['content'])
                self.assertIn('cache invalidation',payload['messages'][1]['content'])
                return {'content':json.dumps({'status':'supported','answer':'Evidence [E1][E2]',
                    'citations':['E1','E2'],'uncertainty':'Partial evidence'}),'tool_calls':None,
                    'finish_reason':'stop','usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        self.provider=Direct()
        value=self.send(self.data)
        self.assertEqual(value['state'],'completed')
        self.assertEqual(value['result']['searches'],1)
        self.assertEqual(value['result']['model_turns'],1)
        self.assertEqual(len(self.provider.calls),1)

    def test_cross_channel_resume_preserves_paid_contract_and_checks_recipient(self):
        self.worker.executor=lambda *a,**kw:execute(*a,provider=self.provider,
            step_limit=None if kw.get('resume') else 2,**kw)
        first=self.send(self.data)
        self.send(self.command('pause'))
        resumed={**self.command('resume'),'channel':'feishu'}
        value=self.send(resumed)
        self.assertEqual(value['state'],'completed')
        self.assertEqual(len(self.provider.calls),2)
        with WorkStore(self.home/'work.sqlite3') as work:
            row=work.db.execute('SELECT run FROM agent_sessions').fetchone()
            self.assertEqual(work.session(row['run'])['channel'],'pwa')

    def test_host_search_checkpoint_replays_without_retrieval_or_payment_repeat(self):
        from unittest.mock import patch
        from personal_asis.retrieval import build_bundle
        with patch('personal_asis.agent.build_bundle',wraps=build_bundle) as lookup:
            first=execute(self.home,'cache','bootstrap-checkpoint',['synthetic'],channel='pwa',
                          bootstrap=True,step_limit=1,provider=self.provider)
            self.assertEqual(first['status'],'checkpointed')
            self.assertEqual(len(self.provider.calls),0)
            self.assertEqual(lookup.call_count,1)
            final=execute(self.home,None,'bootstrap-checkpoint',resume=True,channel='feishu',
                          bootstrap=True,provider=self.provider)
            self.assertEqual(final['status'],'completed')
            # One host search and one later model-selected search; host replay is free.
            self.assertEqual(lookup.call_count,2)
            self.assertEqual(final['result']['searches'],2)
            self.assertEqual(len(self.provider.calls),2)

    def test_old_cited_abstention_resumes_after_validation_fix_without_paid_repeat(self):
        from unittest.mock import patch
        class Abstaining(FakeTools):
            def complete(provider,payload,secret):
                provider.calls.append(payload)
                return {'content':json.dumps({'status':'insufficient_evidence','answer':'Cannot infer [E1]',
                    'citations':['E1'],'uncertainty':'Partial [E2]'}),'tool_calls':None,'finish_reason':'stop',
                    'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}
        self.provider=Abstaining()
        with patch('personal_asis.agent.validate_answer',side_effect=ValueError('model_output_has_invalid_evidence_references:abstention_has_references')):
            first=self.send(self.data)
            self.assertIn('error',first)
        final=self.send(self.command('resume'))
        self.assertEqual(final['state'],'completed')
        self.assertEqual(final['result']['status'],'insufficient_evidence')
        self.assertEqual(final['result']['citations'],[])
        self.assertEqual(len(self.provider.calls),1)


class AgentHttpTests(unittest.TestCase):
    @unittest.skipUnless(CRYPTO,'encrypted reader dependency required')
    def test_owner_and_csrf_are_required_for_control_and_ciphertext(self):
        from test_analysis_http import AnalysisHttpTests
        case=AnalysisHttpTests('test_owner_auth_csrf_node_auth_and_end_to_end_ciphertext_without_server_storage')
        case.setUp()
        self.addCleanup(case.doCleanups)
        data={k:v for k,v in case.data.items() if k!='research'}
        data.update(target_id=str(uuid.uuid4()),action='run',source_ids=['synthetic'])
        self.assertEqual(case.request('/api/agent/request',data)[0],401)
        case.login()
        self.assertEqual(case.request('/api/agent/request',data,{'X-CSRF-Token':'bad'})[0],403)
        self.assertEqual(case.request('/api/agent/request',data)[0],200)
        job=case.client.authenticated('/v1/agent/poll',{'policy_hash':'a'*64,'busy':False})['job']
        self.assertEqual(job['target_id'],data['target_id'])
        case.client.authenticated('/v1/agent/complete',{'request_id':data['request_id'],'lease':job['lease'],
            'status':'ready','envelope':encrypt({'state':'paused'},job,aad(job))})
        result=case.request('/api/agent/result',{'request_id':data['request_id']})
        self.assertEqual(result[0],200)
        self.assertEqual(result[1]['status'],'ready')
        disk=b''.join(p.read_bytes() for p in case.home.glob('*.sqlite3*'))
        self.assertNotIn(b'cache',disk)

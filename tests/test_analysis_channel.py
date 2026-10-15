import base64
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import unittest
import uuid
from unittest.mock import patch

import importlib.util
CRYPTO=importlib.util.find_spec('cryptography') is not None
if CRYPTO:
    from cryptography.hazmat.primitives import hashes,serialization
    from cryptography.hazmat.primitives.asymmetric import padding,rsa
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from personal_asis.analysis_channel import AnalysisRelay,Worker,aad
from personal_asis.coordinator import ProtocolError
from personal_asis.evidence import encrypt,control_server
from personal_asis.feishu import FeishuBridge
from personal_asis.model_provider import MiMo,ProviderUnknown
from personal_asis.pa1 import fixture,configure,analyze,revoke_sources,authorize_current_files


class Provider(MiMo):
    def __init__(self,unknown=False):
        self.calls=0
        self.unknown=unknown
    def credential(self): return 'SYNTHETIC'
    def complete(self,payload,secret):
        self.calls+=1
        if self.unknown: raise ProviderUnknown('timeout')
        return {'content':json.dumps({'answer':'Synthetic evidence [E1]','citations':['E1'],'uncertainty':'limited'}),
                'finish_reason':'stop','tool_calls':None,
                'usage':{'prompt_tokens':100,'completion_tokens':40,'total_tokens':140}}
    def payload(self,bundle,limit):
        return {'messages':[{'role':'user','content':json.dumps(bundle.cloud_input())}]}


@unittest.skipUnless(CRYPTO,'requires encrypted reader dependency')
class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home=fixture(self.tmp.name)
        config=json.loads((self.home/'sources.yaml').read_text())
        config['sources'][0].update(remote_metadata=True,remote_evidence=True)
        (self.home/'sources.yaml').write_text(json.dumps(config))
        configure(self.home,'synthetic-model',True,synthetic_only=False)
        self.now=0
        self.relay=AnalysisRelay(clock=lambda:self.now)
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        self.data={'request_id':str(uuid.uuid4()),'query':'cache','channel':'pwa','source_ids':None,
            'research':None,'client_nonce':base64.b64encode(b'0123456789abcdef').decode(),
            'public_key':base64.b64encode(self.key.public_key().public_bytes(serialization.Encoding.DER,
                serialization.PublicFormat.SubjectPublicKeyInfo)).decode()}

    def decrypt(self,value,key=None,data=None):
        e=value['envelope'];key=key or self.key;data=data or self.data
        raw=key.decrypt(base64.b64decode(e['wrapped_key']),padding.OAEP(mgf=padding.MGF1(hashes.SHA256()),algorithm=hashes.SHA256(),label=None))
        return json.loads(AESGCM(raw).decrypt(base64.b64decode(e['nonce']),base64.b64decode(e['ciphertext']),aad(data)))

    def worker(self,provider):
        relay=self.relay
        class Client:
            def authenticated(self,route,data):
                if route.endswith('/poll'): return relay.poll('mac',data['policy_hash'])
                return relay.complete('mac',data)
        return Worker(self.home,Client(),lambda home,job:analyze(home,job['query'],job['request_id'],provider))

    def test_encrypted_real_pipeline_and_no_plaintext_remote_result(self):
        self.relay.request(self.data)
        provider=Provider()
        self.assertTrue(self.worker(provider).once()['claimed'])
        remote=self.relay.get(self.data['request_id'])
        self.assertNotIn('Synthetic evidence',json.dumps(remote))
        value=self.decrypt(remote)
        self.assertEqual(value['citations'],['E1'])
        self.assertNotIn('original_uri',value['evidence'][0])
        self.assertEqual(provider.calls,1)

    @unittest.skipUnless(shutil.which('node'),'requires Node WebCrypto')
    def test_browser_webcrypto_decodes_analysis_envelope(self):
        value={'answer':'Synthetic WebCrypto 中文 [E1]'}
        envelope=encrypt(value,self.data,aad(self.data))
        private=self.key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
        program="""const {webcrypto}=require('node:crypto');let raw='';process.stdin.on('data',c=>raw+=c);process.stdin.on('end',async()=>{
 const d=JSON.parse(raw),s=webcrypto.subtle,b=x=>Buffer.from(x,'base64');
 const k=await s.importKey('pkcs8',b(d.key),{name:'RSA-OAEP',hash:'SHA-256'},false,['decrypt']);
 const aes=await s.importKey('raw',await s.decrypt({name:'RSA-OAEP'},k,b(d.envelope.wrapped_key)),'AES-GCM',false,['decrypt']);
 const text=await s.decrypt({name:'AES-GCM',iv:b(d.envelope.nonce),additionalData:b(d.context)},aes,b(d.envelope.ciphertext));
 process.stdout.write(Buffer.from(text));});"""
        result=subprocess.run(['node','-e',program],input=json.dumps({'key':base64.b64encode(private).decode(),
            'envelope':envelope,'context':base64.b64encode(aad(self.data)).decode()}),text=True,capture_output=True,check=True,timeout=15)
        self.assertEqual(json.loads(result.stdout),value)

    def test_duplicate_request_conflict_invalid_key_and_credentials(self):
        self.relay.request(self.data)
        self.relay.request(self.data)
        self.assertEqual(len(self.relay.jobs),1)
        for changed in ({'query':'other'},{'public_key':'not-valid-base64'},{'query':'api_key: sk-'+('x'*30)}):
            with self.assertRaises(ProtocolError): self.relay.request({**self.data,**changed})

    def test_recipient_key_checked_on_mac_before_paid_call(self):
        data={**self.data,'public_key':base64.b64encode(b'not-a-public-key'*20).decode()}
        self.relay.request(data)
        provider=Provider()
        self.assertEqual(self.worker(provider).once()['status'],'failed')
        self.assertEqual(provider.calls,0)

    def test_expired_execution_stops_before_model_reservation(self):
        provider=Provider()
        def expired():raise ValueError('analysis_request_expired_before_model')
        with self.assertRaisesRegex(ValueError,'expired_before_model'):
            analyze(self.home,'cache','expired-execution',provider,before_model=expired)
        self.assertEqual(provider.calls,0)

    def test_model_permission_alone_cannot_disclose_through_owner_channel(self):
        config=json.loads((self.home/'sources.yaml').read_text())
        config['sources'][0]['remote_evidence']=False
        (self.home/'sources.yaml').write_text(json.dumps(config))
        provider=Provider()
        with self.assertRaisesRegex(ValueError,'channel_permission_denied'):
            analyze(self.home,'cache','model-only-cannot-disclose',provider,channel='pwa')
        self.assertEqual(provider.calls,0)

    def test_reconnect_reuses_local_result_without_second_paid_call(self):
        provider=Provider();worker=self.worker(provider)
        self.relay.request(self.data);worker.once()
        self.relay.jobs.clear()  # VPS restart / expired transport; durable model state is local.
        self.relay.request(self.data);worker.once()
        value=self.decrypt(self.relay.get(self.data['request_id']))
        self.assertTrue(value['cached']);self.assertEqual(provider.calls,1)

    def test_unknown_call_not_retried_after_transport_restart(self):
        provider=Provider(unknown=True);worker=self.worker(provider)
        self.relay.request(self.data);worker.once()
        self.relay.jobs.clear();self.relay.request(self.data);worker.once()
        value=self.decrypt(self.relay.get(self.data['request_id']))
        self.assertFalse(value['retry_automatically']);self.assertEqual(provider.calls,1)

    def test_policy_revocation_removes_ready_ciphertext(self):
        provider=Provider();worker=self.worker(provider)
        authorize_current_files(self.home,['synthetic'])
        self.relay.request(self.data);worker.once()
        self.assertEqual(self.relay.get(self.data['request_id'])['status'],'ready')
        revoke_sources(self.home,['synthetic']);worker.once()
        self.assertEqual(self.relay.get(self.data['request_id'])['status'],'revoked')
        self.assertIsNone(self.relay.get(self.data['request_id'])['envelope'])

    def test_changed_content_before_cached_disclosure_is_refused(self):
        provider=Provider();worker=self.worker(provider)
        self.relay.request(self.data);worker.once();self.relay.jobs.clear()
        (self.home/'source/cache.md').write_text('changed')
        self.relay.request(self.data);worker.once()
        self.assertIn('error',self.decrypt(self.relay.get(self.data['request_id'])))
        self.assertEqual(provider.calls,1)

    def test_ciphertext_expires_and_original_request_ttl_is_bounded(self):
        self.relay.request(self.data);self.worker(Provider()).once()
        self.now=31
        self.assertEqual(self.relay.get(self.data['request_id'])['status'],'expired')
        self.now=901
        with self.assertRaises(ProtocolError):self.relay.get(self.data['request_id'])

    def test_owner_feishu_decrypts_only_in_memory_and_delivery_is_not_repeated(self):
        import asyncio
        server,path=control_server(self.home,self.relay,'analysis.sock')
        self.addCleanup(path.unlink,missing_ok=True);self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        bridge=FeishuBridge(self.home);self.addCleanup(bridge.close)
        code=bridge.pairing('platform')['pairing_code'];bridge.bind('platform','ou_owner',code)
        with self.assertRaises(ProtocolError):bridge.submit_analysis('platform','ou_other','m','cache')
        task=bridge.submit_analysis('platform','ou_owner','m','cache')
        provider=Provider();self.worker(provider).once()
        rows=bridge.pending_analyses();self.assertEqual(len(rows),1)
        sent=[]
        async def send(*args):sent.append(args);return True
        asyncio.run(bridge.deliver(*rows[0],send))
        asyncio.run(bridge.deliver(*rows[0],send))
        self.assertEqual(len(sent),1);self.assertIn('Synthetic evidence',sent[0][2])
        bridge.close()
        raw=(self.home/'feishu.sqlite3').read_bytes()
        self.assertNotIn(b'Synthetic evidence',raw)
        bridge=FeishuBridge(self.home);self.addCleanup(bridge.close)

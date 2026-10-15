import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid

from personal_asis.transport import server as transport_server
from personal_asis.pwa import server as pwa_server
from personal_asis.node import Client
from personal_asis.coordinator import Coordinator
from personal_asis.analysis_channel import Worker,aad
from personal_asis.pa1 import fixture,configure,analyze
import test_pwa as pwa_tests
from test_analysis_channel import Provider,CRYPTO


class Key:
    def get(self):return 'synthetic_node_enrollment_secret_only'


@unittest.skipUnless(CRYPTO,'requires encrypted reader dependency')
class AnalysisHttpTests(unittest.TestCase):
    request,login=pwa_tests.PwaTests.request,pwa_tests.PwaTests.login

    def setUp(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives import serialization
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)/'server';self.home.mkdir()
        self.mac_home=Path(self.tmp.name)/'mac';self.mac_home.mkdir()
        fixture(self.mac_home);configure(self.mac_home,'synthetic-model',True,synthetic_only=False)
        data=json.loads((self.mac_home/'sources.yaml').read_text())
        data['sources'][0].update(remote_metadata=True,remote_evidence=True)
        (self.mac_home/'sources.yaml').write_text(json.dumps(data))
        transport=transport_server(self.home/'coordinator.sqlite3',port=0)
        threading.Thread(target=transport.serve_forever,daemon=True).start()
        self.addCleanup(transport.server_close);self.addCleanup(transport.shutdown)
        endpoint=f'http://127.0.0.1:{transport.server_port}'
        self.client=Client(endpoint,'mac',Key())
        with Coordinator(self.home/'coordinator.sqlite3') as coordinator:
            code=coordinator.pair('mac')['pairing_code']
        self.client.enroll(code)
        self.http=pwa_server(self.home,port=0,origin='https://example.test',auth_method='password')
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)
        self.cookie,self.csrf='',''
        self.key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        public=self.key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.data={'query':'cache','request_id':str(uuid.uuid4()),'source_ids':None,'research':None,
            'client_nonce':base64.b64encode(b'n'*16).decode(),'public_key':base64.b64encode(public).decode()}

    def test_owner_auth_csrf_node_auth_and_end_to_end_ciphertext_without_server_storage(self):
        from test_analysis_channel import AnalysisTests
        self.assertEqual(self.request('/api/analysis/request',self.data)[0],401)
        self.login()
        self.assertEqual(self.request('/api/analysis/request',self.data,{'X-CSRF-Token':'wrong'})[0],403)
        self.assertEqual(self.request('/api/analysis/request',self.data)[0],200)
        provider=Provider()
        worker=Worker(self.mac_home,self.client,lambda home,job:analyze(home,job['query'],job['request_id'],provider))
        worker.once()
        status,result,_=self.request('/api/analysis/result',{'request_id':self.data['request_id']})
        self.assertEqual(status,200)
        value=AnalysisTests.decrypt(self,result,data={**self.data,'channel':'pwa'})
        self.assertEqual(value['citations'],['E1'])
        self.assertNotIn('original_uri',value['evidence'][0])
        disk=b''.join(p.read_bytes() for p in self.home.glob('*.sqlite3*'))
        self.assertNotIn(b'Synthetic evidence',disk)
        self.assertNotIn(self.data['query'].encode(),disk)
        self.assertEqual(provider.calls,1)

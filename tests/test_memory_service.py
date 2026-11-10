import json
import threading
import unittest
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from personal_asis.memory_service import MemoryHTTPServer
import test_memory_authority as authority_tests


class Ledger:
    def status(self):
        return []


class MemoryHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture=authority_tests.AuthorityTests();self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.server=MemoryHTTPServer(('127.0.0.1',0),self.fixture.authority,
            {'chat':'synthetic-chat','work':'synthetic-work'},Ledger())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self,action,args,token=None,**headers):
        request=Request(f'http://127.0.0.1:{self.server.server_port}/v1/memory',method='POST',
            data=json.dumps(dict(action=action,arguments=args)).encode(),
            headers={'Content-Type':'application/json',**({'Authorization':'Bearer '+token} if token else {}),**headers})
        try:
            with urlopen(request,timeout=3) as r:return r.status,json.load(r)
        except HTTPError as r:
            with r:return r.code,json.load(r)

    def test_authentication_and_origin_are_checked_before_business(self):
        for token in [None,'wrong-token']:
            status,value=self.request('status',{},token)
            self.assertEqual(status,401)
            self.assertEqual(value['error'],'memory_client_denied')
        self.assertEqual(self.request('status',{},'synthetic-chat',Origin='https://untrusted.invalid')[0],409)
        self.assertEqual(self.fixture.extract_calls,0)

    def test_authenticated_shared_scope_and_wrong_identity_parameters(self):
        status,created=self.request('capture',dict(source_id='http-one',text='以后解释用中文。',synthetic=True),'synthetic-chat')
        self.assertEqual(status,200)
        status,found=self.request('search',dict(query='解释语言'),'synthetic-work')
        self.assertEqual(found['records'][0]['id'],created['records'][0]['id'])
        self.assertEqual(self.request('search',dict(query='解释语言',user_id='another-owner'),'synthetic-work')[0],409)

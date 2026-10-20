import http.client
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from personal_asis import conversation as core, pa1
from personal_asis.conversation_web import server


class ConversationWebClientTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'requires Node for synthetic DOM smoke test')
    def test_client_initializes_binds_controls_sends_and_renders(self):
        result = subprocess.run(['node', str(Path(__file__).with_name('conversation-web-ui.cjs'))],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class ConversationWebTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=pa1.fixture(self.tmp.name)
        self.http=server(self.home)
        thread=threading.Thread(target=self.http.serve_forever,daemon=True);thread.start()
        self.addCleanup(self.http.server_close);self.addCleanup(self.http.shutdown)

    def request(self,path,body=None,headers=None):
        port=self.http.server_port
        h={'Host':f'127.0.0.1:{port}','Origin':f'http://127.0.0.1:{port}'}
        if body is not None:h['Content-Type']='application/json'
        h.update(headers or {})
        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=3)
        conn.request('POST' if body is not None else 'GET',path,
                     json.dumps(body) if body is not None else None,h)
        res=conn.getresponse();raw=res.read();status=res.status;headers=dict(res.getheaders());conn.close()
        return status,raw,headers

    def test_local_chat_shell_and_session_api_are_same_origin_only(self):
        status,raw,headers=self.request('/chat')
        self.assertEqual(status,200);self.assertIn('直接输入消息'.encode(),raw)
        self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(self.request('/api/session/new',{})[0],200)
        status,raw,_=self.request('/api/session/new',{}, {'Origin':'http://attacker.test'})
        self.assertEqual(status,403)
        status,raw,_=self.request('/',headers={'Host':'attacker.test'})
        self.assertEqual(status,403)

    def test_session_read_and_event_cursor_are_bounded(self):
        with core.ConversationStore(self.home) as store:
            sid=store.create();store.event(sid,'synthetic-turn','tool_start',{'tool':'search_notes','query':'private'})
        status,raw,_=self.request('/api/session?id='+sid)
        self.assertEqual(status,200);self.assertEqual(json.loads(raw)['turns'],[])
        status,raw,headers=self.request('/api/events?id='+sid+'&after=0')
        self.assertEqual(status,200);self.assertIn('text/event-stream',headers['Content-Type'])
        self.assertIn(b'"tool": "search_notes"',raw);self.assertNotIn(b'private',raw)

    def test_session_picker_lists_only_metadata_and_forget_clears_content(self):
        with core.ConversationStore(self.home) as store:
            sid=store.create();store.event(sid,'synthetic-turn','turn_completed')
        status,raw,_=self.request('/api/sessions')
        self.assertEqual(status,200)
        listing=json.loads(raw)['sessions']
        self.assertEqual([row['id'] for row in listing],[sid])
        self.assertEqual(set(listing[0]),{'id','at'})
        status,raw,_=self.request('/api/control',{'session_id':sid,'action':'forget','turn_id':'forget-session'})
        self.assertEqual(status,200)
        status,raw,_=self.request('/api/session?id='+sid)
        self.assertEqual(json.loads(raw)['turns'],[])
        from personal_asis.conversation_api import ConversationAPI
        self.assertEqual(ConversationAPI(self.home).events(sid)['events'],[])


if __name__=='__main__':unittest.main()

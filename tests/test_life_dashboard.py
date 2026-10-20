import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from personal_asis.dashboard import server,snapshot
from personal_asis.life_store import LifeStore
from personal_asis.web_auth import WebAuth


class DashboardTests(unittest.TestCase):
    def test_authentication_readonly_routes_xss_and_no_source_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp)
            store=LifeStore(home/'life.sqlite3')
            store.capture('platform','owner','one','<script>synthetic</script>')
            store.close()
            with WebAuth(home,otp_required=False) as auth:
                token=auth.bootstrap()['setup_token']
                auth.setup_finish(token,'synthetic-long-password','','fixture')
            srv=server(home,'https://dashboard.example',0)
            thread=threading.Thread(target=srv.serve_forever,daemon=True);thread.start()
            try:
                c=http.client.HTTPConnection('127.0.0.1',srv.server_port)
                headers={'Host':'dashboard.example','X-Forwarded-Proto':'https'}
                c.request('GET','/api/dashboard',headers=headers)
                r=c.getresponse();self.assertEqual(r.status,401);self.assertNotIn(b'synthetic',r.read())
                c.request('POST','/auth/login',json.dumps({'password':'synthetic-long-password'}),{**headers,'Origin':'https://evil.example'})
                r=c.getresponse();self.assertEqual(r.status,403);r.read()
                c.request('POST','/auth/login',json.dumps({'password':'synthetic-long-password'}),{**headers,'Origin':'https://dashboard.example'})
                r=c.getresponse();self.assertEqual(r.status,200)
                cookie=r.getheader('Set-Cookie').split(';')[0];r.read()
                self.assertIn('HttpOnly',r.getheader('Set-Cookie'))
                c.request('GET','/api/dashboard',headers={**headers,'Cookie':cookie})
                r=c.getresponse();self.assertEqual(r.status,200)
                body=json.loads(r.read());self.assertEqual(body['astrbot']['records'][0]['text'],'<script>synthetic</script>')
                self.assertNotIn(str(home),json.dumps(body))
                self.assertEqual(r.getheader('Cache-Control'),'no-store')
                for path in ('/api/search','/api/agent','/api/evidence'):
                    c.request('POST',path,'{}',{**headers,'Cookie':cookie,'Origin':'https://dashboard.example'})
                    r=c.getresponse();self.assertEqual(r.status,404);r.read()
            finally:
                srv.shutdown();srv.server_close();thread.join()

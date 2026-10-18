import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import reading
from personal_asis.reading_sources import SourceError
from personal_asis.social_reading import XiaoHongShuOpenCLI


class Key:
    value = ''
    def get(self): return self.value
    def set(self, value): self.value = value


class OpenCLIReadingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.entry = self.home/'dist/src/main.js'
        self.entry.parent.mkdir(parents=True)
        self.entry.write_text('// synthetic entry')
        self.key = Key()
        self.api = XiaoHongShuOpenCLI(self.entry, '/usr/bin/true', access_store=lambda item:self.key)
        self.item = 'abcdef0123456789abcdef01'

    def row(self):
        return {'id':self.item, 'title':'Synthetic article', 'author':'Synthetic author',
                'url':f'https://www.xiaohongshu.com/explore/{self.item}?xsec_token=PRIVATE_TEST_SIGNATURE'}

    def test_signed_url_stays_in_keychain_not_evidence(self):
        page = self.api.articles([self.row()], 2)
        self.assertIsNone(page.more)
        self.assertEqual(self.key.value, self.row()['url'])
        self.assertNotIn('PRIVATE_TEST_SIGNATURE', str(page.articles[0]))
        self.assertNotIn('?', page.articles[0].url)
        self.assertEqual(page.articles[0].content_kind,'metadata_only')

    def test_note_secret_only_on_stdin_and_trace_disabled_in_bridge(self):
        seen=[]
        def runner(argv,**kwargs):
            seen.append((argv,kwargs))
            rows=[{'field':k,'value':v} for k,v in
                  {'title':'Synthetic article','author':'Synthetic author','content':'Actual note text'}.items()]
            return subprocess.CompletedProcess(argv,0,json.dumps(rows).encode(),b'')
        self.api.runner=runner
        self.key.value=self.row()['url']
        article=self.api.detail(self.item)
        argv,kwargs=seen[0]
        self.assertNotIn(self.key.value,' '.join(argv))
        self.assertNotIn(self.key.value,str(kwargs['env']))
        self.assertIn(self.key.value,kwargs['input'].decode())
        request=json.loads(kwargs['input'])
        self.assertEqual(request['operation'],'note')
        self.assertEqual(article.content_kind,'note_text')
        self.assertNotIn('PRIVATE_TEST_SIGNATURE',str(article))

    def test_saved_profile_path_kept_only_in_keychain_and_identity_checked(self):
        url=f'https://www.xiaohongshu.com/user/profile/{"b"*24}/{self.item}?xsec_token=PRIVATE_TEST_SIGNATURE&xsec_source=pc_user'
        page=self.api.articles([{**self.row(),'url':url}],2)
        self.assertEqual(self.key.value,url)
        self.assertEqual(page.articles[0].url,'https://www.xiaohongshu.com/explore/'+self.item)
        with self.assertRaises(SourceError):self.api.articles([{**self.row(),'url':url.replace(self.item,'a'*24)}],2)

    def test_wrong_origin_identity_and_remote_errors_rejected(self):
        for update in ({'url':'https://example.com/explore/'+self.item}, {'id':'f'*24}):
            with self.assertRaises(SourceError):self.api.articles([{**self.row(),**update}],2)
        self.api.runner=lambda *a,**kw:subprocess.CompletedProcess(a,1,b'PRIVATE_TEST_SIGNATURE',b'PRIVATE_TEST_SIGNATURE')
        with self.assertRaisesRegex(SourceError,'^reading_opencli_read_failed$'):self.api.call('feed')

    def test_write_operations_history_and_followed_filter_not_claimed(self):
        for operation in ('like','follow','publish','notifications','login','ask'):
            with self.assertRaises(SourceError):self.api.call(operation)
        with self.assertRaises(SourceError):self.api.page('subscriptions',cursor='next')
        with self.assertRaises(SourceError):self.api.search('systems',followed_only=True)

    def test_backend_binding_and_status_do_not_read_browser_or_mcp_credentials(self):
        reading.configure(self.home,'xiaohongshu',xhs_opencli=self.entry,xhs_node=Path('/usr/bin/true'))
        reading.activate(self.home,'xiaohongshu')
        with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('no credential lookup')):
            report=reading.status(self.home,'xiaohongshu')
            with reading.ReadingCache(self.home,'xiaohongshu') as cache:
                self.assertIsInstance(reading.client(cache),XiaoHongShuOpenCLI)
        self.assertEqual(report['credential'],'owner_browser_session_not_checked')
        self.assertEqual(report['backend'],'opencli')


if __name__=='__main__':unittest.main()

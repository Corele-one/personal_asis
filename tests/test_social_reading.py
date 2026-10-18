import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import reading
from personal_asis.reading_sources import SourceError
from personal_asis.social_reading import (WeChat, XiaoHongShu, Zhihu, wechat_url, xhs_endpoint)


class Key:
    def __init__(self, value='SYNTHETIC_SECRET_ONLY'):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class SocialReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()

    def test_configuration_defers_platform_and_credential_access(self):
        for connector in ('zhihu', 'xiaohongshu'):
            reading.configure(self.home, connector)
            with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('no credential read')):
                status = reading.status(self.home, connector)
                self.assertEqual(status['account_access'], 'deferred')
                self.assertEqual(status['credential'], 'not_checked')
                with self.assertRaisesRegex(SourceError, 'authorization_deferred'):
                    reading.sync(self.home, connector)
                with self.assertRaisesRegex(SourceError, 'authorization_deferred'):
                    reading.fetch(self.home, connector, 'one')
        self.assertFalse(list((self.home/'reading-cache').rglob('*.md')))

    def test_deferred_folo_preserves_existing_sources_and_does_not_read_token(self):
        reading.configure(self.home, 'wucai')
        before = json.loads((self.home/'sources.yaml').read_text())['sources'][0]
        reading.configure(self.home, 'folo', folo_cli=Path('/usr/bin/true'), defer_auth=True)
        after = json.loads((self.home/'sources.yaml').read_text())['sources'][0]
        self.assertEqual(before, after)
        with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('no credentials')):
            self.assertEqual(reading.status(self.home, 'folo')['credential'], 'not_checked')

    def test_activation_is_local_and_separate_from_account_verification(self):
        reading.configure(self.home, 'zhihu', zhihu_cli=Path('/usr/bin/true'))
        with patch('personal_asis.credentials.CredentialStore.get', side_effect=AssertionError('no credentials')):
            value = reading.activate(self.home, 'zhihu')
        self.assertFalse(value['account_verified'])
        with reading.ReadingCache(self.home, 'zhihu') as cache:
            self.assertIsInstance(reading.client(cache), Zhihu)

    def test_zhihu_offset_and_summary_are_not_invented_fulltext(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append((argv, kwargs))
            data = {'Code': 0, 'Data': {'Items': [{'Url':'https://www.zhihu.com/answer/123',
                'Title':'Example', 'Summary':'author summary', 'Author':{'Name':'Example author'}}],
                'Paging': {'IsEnd':False, 'NextOffset':'37'}}}
            return subprocess.CompletedProcess(argv, 0, json.dumps(data).encode(), b'')
        api = Zhihu('/usr/bin/true', collection_id='123', store=Key(), runner=runner)
        page = api.page('selections', cursor='9', limit=20)
        self.assertEqual(page.cursor, '37')
        self.assertTrue(page.more)
        self.assertEqual(page.articles[0].content_kind, 'summary_only')
        self.assertEqual(page.articles[0].author, 'Example author')
        argv, kwargs = seen[0]
        self.assertEqual(argv[argv.index('--offset')+1], '9')
        self.assertNotIn(Key().get(), ' '.join(argv))
        self.assertEqual(kwargs['env']['ZHIHU_ACCESS_SECRET'], Key().get())

    def test_zhihu_recent_does_not_claim_history_paging(self):
        api = Zhihu('/usr/bin/true')
        with patch.object(api, 'call', return_value={'Items': []}):
            page = api.page('selections')
            self.assertIsNone(page.more)
        with self.assertRaisesRegex(SourceError, 'timeline_not_supported'):
            api.page('subscriptions')

    def test_zhihu_rejects_unverified_or_backward_paging(self):
        api = Zhihu('/usr/bin/true', collection_id='123')
        for paging in ({'IsEnd':False}, {'IsEnd':False,'NextOffset':'2'},
                       {'IsEnd':False,'NextOffset':'NaN'}):
            with patch.object(api, 'call', return_value={'Items': [],'Paging':paging}):
                with self.assertRaisesRegex(SourceError, 'schema_unverified'):
                    api.page('selections', cursor='2')

    def test_zhihu_does_not_enable_write_or_hidden_model_commands(self):
        api = Zhihu('/usr/bin/true', store=Key(), runner=lambda *a,**k:self.fail('must not execute'))
        for operation in ('knowledge upload','answer','auth set','upgrade'):
            with self.assertRaisesRegex(SourceError, 'denied'):
                api.call(operation)
        with self.assertRaisesRegex(SourceError, 'explicit_owner'):
            api.detail('123')

    def test_zhihu_business_failure_is_not_empty_success_and_error_is_redacted(self):
        def runner(argv, **kwargs):
            raw = json.dumps({'Code':20001,'Message':Key().get(),'Data':{}}).encode()
            return subprocess.CompletedProcess(argv, 0, raw, b'')
        with self.assertRaisesRegex(SourceError, '^reading_zhihu_request_failed$'):
            Zhihu('/usr/bin/true', store=Key(), runner=runner).page('selections')

    def test_xhs_only_loopback_endpoint_and_no_login_or_notification_tools(self):
        for url in ('http://0.0.0.0:18060/mcp','https://example.org/mcp',
                    'http://localhost:18060/mcp','http://127.0.0.1:18060/mcp?x=1'):
            with self.assertRaises(SourceError):
                xhs_endpoint(url)
        api = XiaoHongShu('http://127.0.0.1:18060/mcp')
        for op in ('list_notifications','get_login_qrcode','check_login_status','like_feed',
                   'favorite_feed','publish_content','delete_cookies'):
            with self.assertRaisesRegex(SourceError, 'denied'):
                api.call(op, {})

    def test_xhs_mcp_handshake_session_and_readonly_call(self):
        class Response(io.BytesIO):
            def __init__(self, data):
                super().__init__(data)
                self.headers = {'Mcp-Session-Id':'synthetic-session'}
        class Opener:
            def __init__(self):self.requests=[]
            def open(self, request, timeout):
                payload=json.loads(request.data);self.requests.append((request,payload))
                if payload['method']=='notifications/initialized':return Response(b'')
                result = {'protocolVersion':'2024-11-05'} if payload['method']=='initialize' else {
                    'content':[{'type':'text','text':json.dumps({'feeds':[]})}]}
                return Response(json.dumps({'jsonrpc':'2.0','id':payload['id'],'result':result}).encode())
        opener=Opener()
        api=XiaoHongShu('http://127.0.0.1:18060/mcp',store=Key(),opener=opener)
        self.assertIsNone(api.page('selections').more)
        self.assertEqual([p['method'] for _,p in opener.requests],['initialize','notifications/initialized','tools/call'])
        request,payload=opener.requests[-1]
        self.assertEqual(payload['params'],{'name':'get_my_profile','arguments':{'tab':'fav'}})
        self.assertEqual(request.get_header('Mcp-session-id'),'synthetic-session')

    def test_xhs_followed_search_remains_visible_results_and_tokens_outside_cache(self):
        stores={}
        api=XiaoHongShu('http://127.0.0.1:18060/mcp',access_store=lambda key:stores.setdefault(key,Key()))
        data={'feeds':[{'id':'abc','xsecToken':'SYNTHETIC_NOTE_TOKEN',
                       'noteCard':{'displayTitle':'Example','user':{'nickname':'Author'}}}]}
        with patch.object(api,'call',return_value=data) as call:
            page=api.search('explicit topic',True,1)
            self.assertEqual(call.call_args.args[1]['filters'],{'search_scope':'已关注'})
        self.assertIsNone(page.more)
        self.assertEqual(stores['abc'].get(),'SYNTHETIC_NOTE_TOKEN')
        self.assertNotIn('TOKEN',page.articles[0].url)
        self.assertEqual(page.articles[0].content_kind,'metadata_only')

    def test_xhs_detail_does_not_load_extra_comments_or_interpret_media(self):
        api=XiaoHongShu('http://127.0.0.1:18060/mcp',access_store=lambda key:Key())
        data={'data':{'note':{'noteId':'abc','title':'Title','desc':'Visible note text',
            'imageList':[{'urlDefault':'https://example.org/image.jpg'}],
            'video':{'media':{'stream':{'h264':[{'backupUrls':['https://example.org/video.mp4']} ]}}}}}}
        with patch.object(api,'call',return_value=data) as call:
            item=api.detail('abc')
            self.assertIs(call.call_args.args[1]['load_all_comments'],False)
        self.assertEqual(item.content_kind,'note_text')
        self.assertEqual(item.author_text,'Visible note text')
        self.assertEqual(len(item.media_urls),2)

    def test_wechat_public_link_validation_excludes_login_parameters_and_other_hosts(self):
        canonical=wechat_url('https://mp.weixin.qq.com/s/ABCdef_123?scene=1')
        self.assertEqual(canonical,'https://mp.weixin.qq.com/s/ABCdef_123')
        for url in ('https://evil.org/s/ABCdef_123','http://mp.weixin.qq.com/s/ABCdef_123',
                    'https://mp.weixin.qq.com/s/ABCdef_123?pass_ticket=SECRET',
                    'https://mp.weixin.qq.com/s/ABCdef_123?key=SECRET'):
            with self.assertRaises(SourceError):wechat_url(url)

    def test_wechat_extracts_visible_article_not_scripts_or_login_challenge(self):
        html='<meta property="og:title" content="Example"><div>Outside</div><div id="js_content"><p>Author text</p><script>secret script</script><p>Next line</p></div><p>Footer</p>'
        item=WeChat.article('https://mp.weixin.qq.com/s/ABCdef_123',html)
        self.assertEqual(item.author_text,'Author text\nNext line')
        self.assertEqual(item.content_kind,'page_text')
        self.assertEqual(item.title,'Example')
        with self.assertRaisesRegex(SourceError,'unavailable_or_requires_login'):
            WeChat.article('https://mp.weixin.qq.com/s/ABCdef_123','<html>Please log in</html>')

    def test_wechat_share_reuses_existing_local_index_and_no_implicit_grants(self):
        reading.configure(self.home,'wechat')
        with self.assertRaisesRegex(SourceError,'share_link_required'):
            reading.fetch(self.home,'wechat','one')
        class FakePage:
            def share(self,url):return WeChat.article(url,'<div id="js_content">synthetic article cache</div>')
        result=reading.share(self.home,'wechat','https://mp.weixin.qq.com/s/ABCdef_123',FakePage())
        self.assertEqual(result['outcome'],'stored')
        from personal_asis.config import load_config
        from personal_asis.index import Index
        config=load_config(self.home/'sources.yaml')
        self.assertFalse(config.sources[0].remote_metadata)
        self.assertFalse(config.sources[0].model_providers)
        with Index(self.home/'index.sqlite3',config) as index:
            self.assertTrue(index.search('synthetic','local')['results'])
            self.assertFalse(index.search('synthetic','pwa')['results'])


if __name__=='__main__':
    unittest.main()

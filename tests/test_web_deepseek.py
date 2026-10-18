from datetime import datetime,timezone
import json
import unittest

from personal_asis.web_deepseek import DeepSeekProvider
from personal_asis.web_search import WebError
from personal_asis.agent_web import policy


URL='https://example.org/public'
class Key:
    def get(self):return 'SYNTHETIC_DEEPSEEK_KEY'

class HTTP:
    def __init__(self,date=None):self.calls=[];self.date=date;self.redirect=False;self.block=False
    def request(self,url,**kwargs):
        self.calls.append((url,kwargs))
        if url=='https://api.deepseek.com/v1/tools/search':
            return url,json.dumps({'results':[{'url':URL,'title':'Public','snippet':'Discovery only',
                'content':'Public body evidence. '*200,'date':self.date,'authority':4}]}).encode(),'application/json'
        if self.block:raise WebError('web_dns_nonpublic_or_unavailable')
        return ('https://example.org/redirected' if self.redirect else url),b'<p>'+b'Fallback public text. '*20+b'</p>','text/html'


class DeepSeekTests(unittest.TestCase):
    def test_structured_search_hides_body_until_local_verified_read(self):
        http=HTTP();api=DeepSeekProvider(http,Key())
        result=api.search_web('public query',1)
        payload=json.loads(http.calls[0][1]['body'])
        self.assertEqual(payload,{'query':'public query','count':1,'need_content':True})
        self.assertNotIn('content',result['results'][0])
        self.assertIn(URL,result['pages'])
        body=api.fetch_web(URL,300)
        self.assertEqual(body['reader'],'deepseek_search_body_local_target_verified')
        self.assertEqual(len(body['excerpt']),300)
        self.assertNotIn('credential',http.calls[1][1])
        self.assertEqual(body['content_completeness'],'partial')

    def test_saved_public_body_never_bypasses_target_denial(self):
        http=HTTP();api=DeepSeekProvider(http,Key());api.search_web('public query',1)
        http.block=True
        with self.assertRaises(WebError):api.fetch_web(URL)

    def test_changed_redirect_or_expired_snapshot_uses_static_body(self):
        for expired in (False,True):
            http=HTTP();api=DeepSeekProvider(http,Key());api.search_web('public query',1)
            if expired:api.pages[URL]['fetched_at']='2000-01-01T00:00:00+00:00'
            else:http.redirect=True
            body=api.fetch_web(URL)
            self.assertEqual(body['reader'],'local_static_no_matching_provider_body')
            self.assertIn('Fallback',body['excerpt'])

    def test_unknown_dates_fail_closed_for_recent_queries(self):
        result=DeepSeekProvider(HTTP(),Key()).search_web('public query',1,7)
        self.assertEqual(result['results'],[]);self.assertEqual(result['pages'],{})

    def test_query_length_and_personal_terms_rejected_before_network(self):
        http=HTTP();api=DeepSeekProvider(http,Key())
        for query in ('x'*129,'我的日记内容'):
            with self.assertRaises(WebError):api.search_web(query,1)
        self.assertEqual(http.calls,[])
        with self.assertRaises(ValueError):policy(['x'*129],'deepseek')

    def test_public_snapshots_restore_without_another_paid_search(self):
        http=HTTP();first=DeepSeekProvider(http,Key()).search_web('public query',1)
        restored=DeepSeekProvider(http,Key(),json.loads(json.dumps(first['pages'])))
        restored.fetch_web(URL,200)
        self.assertEqual(sum(c[0].endswith('/tools/search') for c in http.calls),1)

    def test_bad_publication_date_does_not_drop_untimed_evidence(self):
        result=DeepSeekProvider(HTTP(date='not-a-date'),Key()).search_web('public query',1)
        self.assertEqual(len(result['results']),1)
        self.assertIsNone(result['results'][0]['published_at'])
        self.assertFalse(DeepSeekProvider(HTTP(date='not-a-date'),Key()).search_web('public query',1,7)['results'])

    def test_http_discovery_upgrades_without_trusting_old_body(self):
        class HttpDiscovery(HTTP):
            def request(self,url,**kwargs):
                final,raw,kind=super().request(url,**kwargs)
                if url.endswith('/tools/search'):
                    value=json.loads(raw);value['results'][0]['url']=URL.replace('https:','http:');raw=json.dumps(value).encode()
                return final,raw,kind
        http=HttpDiscovery();api=DeepSeekProvider(http,Key());result=api.search_web('public query',1)
        self.assertEqual(result['results'][0]['url'],URL);self.assertFalse(result['pages'])
        self.assertIn('local_static',api.fetch_web(URL)['reader'])

    def test_public_anchor_is_not_sent_to_network(self):
        class Anchor(HTTP):
            def request(self,url,**kwargs):
                final,raw,kind=super().request(url,**kwargs)
                if url.endswith('/tools/search'):
                    value=json.loads(raw);value['results'][0]['url']=URL+'#section';raw=json.dumps(value).encode()
                return final,raw,kind
        http=Anchor();api=DeepSeekProvider(http,Key());result=api.search_web('public query',1)
        self.assertEqual(result['results'][0]['url'],URL)
        self.assertIn('deepseek_search_body',api.fetch_web(URL)['reader'])
        self.assertEqual(http.calls[-1][0],URL)

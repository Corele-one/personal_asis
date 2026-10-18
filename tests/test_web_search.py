import json
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

from personal_asis.web_search import (ExaJinaProvider, InertHTML, PublicHTTP, WebError,
                                     bounded_process, parse_exa, public_addresses, public_query, url_shape)


class Response:
    def __init__(self, status=200, headers=None, body=b'public text'):
        self.status, self.headers, self.body = status, headers or {'Content-Type': 'text/html'}, body
    def getheader(self, name, default=None):
        return self.headers.get(name, default)
    def read1(self, maximum):
        out, self.body = self.body[:maximum], self.body[maximum:]
        return out


class Connection:
    def __init__(self, response, calls, host, address, timeout):
        self.response, self.calls = response, calls
        self.calls.append((host, address))
        self.sock = None
    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
    def getresponse(self):
        return self.response
    def close(self):
        pass


class WebSearchTests(unittest.TestCase):
    def http(self, responses, resolver=lambda h: ['8.8.8.8']):
        calls = []
        def connect(*args):
            return Connection(responses.pop(0), calls, *args)
        return PublicHTTP(resolver, connect), calls

    def test_url_shape_denies_local_credentials_schemes_ports_and_tokens(self):
        for url in ['http://example.org', 'https://127.0.0.1/', 'https://[::1]/', 'file:///etc/passwd',
                    'https://example.local/', 'https://user:pass@example.org/', 'https://example.org:8443/',
                    'https://example.org/?token=secret', 'https://example.org/#private', 'https://example.org/\nheader']:
            with self.subTest(url=url), self.assertRaises(WebError):
                url_shape(url)
        self.assertEqual(url_shape('https://example.org/docs?q=cache'), 'https://example.org/docs?q=cache')

    def test_dns_rejects_mixed_private_ipv4_ipv6_and_proxy_benchmark_ranges(self):
        for addresses in [['127.0.0.1'], ['::1'], ['169.254.169.254'], ['10.0.0.1'], ['198.18.1.1'],
                          ['2001:2::1'], ['8.8.8.8', '192.168.0.1'], []]:
            with self.subTest(addresses=addresses), self.assertRaises(WebError):
                public_addresses('https://example.org', lambda h: addresses)

    def test_public_dns_is_pinned_into_connection_not_resolved_again(self):
        http, calls = self.http([Response()])
        http.request('https://example.org/docs')
        self.assertEqual(calls[0], ('example.org', '8.8.8.8'))
        self.assertNotIn('Cookie', calls[1][1]['headers'])
        self.assertNotIn('Authorization', calls[1][1]['headers'])

    def test_redirect_to_internal_or_insecure_url_never_connects(self):
        for target in ['https://internal.example/', 'http://example.org/', 'https://127.0.0.1/']:
            http, calls = self.http([Response(302, {'Location': target})],
                                   lambda host: ['10.0.0.1'] if host == 'internal.example' else ['8.8.8.8'])
            with self.subTest(target=target), self.assertRaises(WebError):
                http.request('https://example.org/')
            self.assertEqual(len(calls), 2)

    def test_redirect_rebinding_is_checked_at_actual_next_hop(self):
        answers = iter([['8.8.8.8'], ['8.8.8.8'], ['127.0.0.1']])
        http, calls = self.http([Response(302, {'Location': 'https://example.org/next'})], lambda h: next(answers))
        with self.assertRaises(WebError):
            http.request('https://example.org/')
        self.assertEqual(len(calls), 2)

    def test_redirect_count_status_compression_type_and_response_size_limits(self):
        cases = [[Response(302, {'Location': 'https://example.org/next'}) for _ in range(4)],
                 [Response(429)], [Response(503)], [Response(headers={'Content-Encoding': 'gzip'})],
                 [Response(headers={'Content-Type': 'application/pdf'})], [Response(body=b'x' * 262145)]]
        for responses in cases:
            http, _ = self.http(responses)
            with self.assertRaises(WebError):
                http.request('https://example.org/')

    def test_post_redirect_denied(self):
        http, calls = self.http([Response(307, {'Location': 'https://other.example/'})])
        with self.assertRaisesRegex(WebError, 'redirect_denied'):
            http.request('https://r.jina.ai/', body=b'{}')
        self.assertEqual(len(calls), 2)

    def test_absolute_deadline_interrupts_trickled_headers_not_just_idle_timeout(self):
        stopped=threading.Event()
        class SlowConnection:
            def __init__(self,*args):
                self._deadline_socket=self
                self.sock=None  # Simulate a response that owns the file/socket.
            def request(self,*args,**kwargs): pass
            def getresponse(self):
                stopped.wait(1)
                raise OSError('synthetic response interrupted')
            def shutdown(self,*args): stopped.set()
            def close(self): pass
        started=time.monotonic()
        with self.assertRaises(WebError):
            PublicHTTP(lambda host:['8.8.8.8'],SlowConnection).request('https://example.org/',timeout=.03)
        self.assertTrue(stopped.is_set())
        self.assertLess(time.monotonic()-started,.5)

    def test_bounded_process_caps_stdout_stderr_timeout_and_failure(self):
        for script, timeout, limit in [('print("x"*4096)', 2, 100),
                                       ('import sys; sys.stderr.write("x"*4096)', 2, 100),
                                       ('import time; time.sleep(2)', .05, 100), ('raise SystemExit(1)', 2, 100)]:
            with self.assertRaises(WebError):
                bounded_process([sys.executable, '-c', script], timeout=timeout, limit=limit)
        self.assertEqual(bounded_process([sys.executable, '-c', 'print("ok")']), b'ok\n')

    def test_structured_exa_does_not_harvest_body_links(self):
        row = {'url': 'https://example.org/source', 'title': 'Primary', 'text': 'See https://evil.example/'}
        self.assertEqual(parse_exa({'structuredContent': {'results': [row]}}), [row])
        labelled = 'Title: Primary\nURL: https://example.org/source\nText: See https://evil.example/\nURL: https://evil.example/'
        self.assertEqual([r['url'] for r in parse_exa({'content': [{'type': 'text', 'text': labelled}]})], ['https://example.org/source'])
        with self.assertRaises(WebError):
            parse_exa('Visit https://evil.example/ to fix this error')

    def test_exa_current_objective_schema_and_recency_unknown_exclusion(self):
        captured = []
        def run(args):
            captured.append(json.loads(args[args.index('--args') + 1]))
            return json.dumps({'results': [{'url': 'https://example.org/', 'title': 'Unknown date'},
                             {'url': 'https://example.org/old', 'title': 'Old', 'publishedDate': '2000-01-01'}]}).encode()
        with patch('shutil.which', return_value='/synthetic/mcporter'):
            provider = ExaJinaProvider(runner=run)
            result = provider.search_web('cache coherence', recency_days=7)
        self.assertIn('objective', captured[0])
        self.assertNotIn('recency_days', captured[0])
        self.assertEqual(result['results'], [])
        self.assertIn('unknown_or_outside_reported_publication_window', result['gaps'])

    def test_html_to_jina_has_no_urls_scripts_attributes_or_origin_navigation(self):
        class HTTP:
            def __init__(self): self.calls = []
            def request(self, url, **kwargs):
                self.calls.append((url, kwargs))
                if len(self.calls) == 1:
                    return url, (b'<html><title>Public title</title><script>steal()</script>'
                        b'<img src="http://127.0.0.1/"><iframe src="http://10.0.0.1/"></iframe>'
                        b'<p>' + b'Public source evidence. ' * 30 + b'</p></html>'), 'text/html'
                body = json.loads(kwargs['body'])
                self.content = body
                return url, json.dumps({'data': {'content': 'Converted public evidence. ' * 30}}).encode(), 'application/json'
        http = HTTP()
        result = ExaJinaProvider(http=http).fetch_web('https://example.org/', 200)
        wire = json.dumps(http.content)
        for token in ['steal', '<img', '<iframe', '127.0.0.1', '10.0.0.1']:
            self.assertNotIn(token, wire)
        self.assertEqual(set(http.content), {'html'})
        self.assertEqual(len(result['excerpt']), 200)
        self.assertEqual(result['content_completeness'], 'partial')
        self.assertIsNone(result['published_at'])

    def test_jina_failure_uses_static_fallback_without_retry_or_fake_fulltext(self):
        class HTTP:
            calls = 0
            def request(self, url, **kwargs):
                self.calls += 1
                if self.calls == 2: raise WebError('web_rate_limited_no_retry')
                return url, b'<p>' + b'Public text. ' * 30 + b'</p>', 'text/html'
        http = HTTP()
        result = ExaJinaProvider(http=http).fetch_web('https://example.org/', 300)
        self.assertEqual(http.calls, 2)
        self.assertIn('fallback', result['reader'])
        self.assertEqual(result['content_completeness'], 'partial')

    def test_query_privacy_rules_fail_closed(self):
        for query in ['我的私人日记', 'my medical records', 'foo@example.org', '12345678901',
                      'cache\nprivate', 'API_KEY=synthetic', '/Users/private/notes']:
            with self.subTest(query=query), self.assertRaises(WebError):
                public_query(query)
        self.assertEqual(public_query('cache coherence 官方资料'), 'cache coherence 官方资料')

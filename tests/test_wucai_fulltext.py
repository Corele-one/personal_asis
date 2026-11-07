import json
from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from personal_asis import wucai_fulltext as w


HOST = 'https://ps1wcbj.oss-cn-beijing.aliyuncs.com/synthetic?Expires=2000&Signature=synthetic'


def api(data=None, code=1):
    return json.dumps(dict(code=code, data=data)).encode()


def blob(text, metadata='合成😀元数据'):
    return (str(len(metadata.encode('utf-16-le')) // 2) + ':' + metadata + text).encode()


def note(key='sample', **extra):
    return dict(noteIdX=key, title='合成文章', url='https://example.test/article', sou=HOST, **extra)


class Opener:
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    def open(self, request, timeout):
        self.calls.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, size):
                return response[:size]
        return Response()


class FullTextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / 'cache'
        self.sleeps = []

    def client(self, opener, token='synthetic-sync-token'):
        return w.Clippings(token, self.path, opener=opener, clock=lambda: 1000, pause=self.sleeps.append)

    def seed(self, client, entries=None, **extra):
        entries = entries if entries is not None else {'sample': dict(title='合成文章', url='https://example.test/article', sou=HOST, observed_at=1000)}
        w.save(client.path, dict(binding=client.binding, entries=entries, cursor='cursor', scanning=False, gap=5, **extra))

    def test_decodes_utf16_header_and_rejects_malformed_html_empty(self):
        self.assertEqual(w.decode_clipping(blob('正文😀')), '正文😀')
        for raw in [b'plain body', b'xx:body', b'99:x', blob(''), blob('<html>login</html>'), b'\xff']:
            with self.subTest(raw=raw), self.assertRaises(w.FullTextError):
                w.decode_clipping(raw)

    def test_lookup_reads_only_requested_blob_and_never_sends_token_to_storage(self):
        op = Opener(api(dict(lastCursor2='old-service-cursor', gapTime=5)),
                    api(dict(notes=[note('other'), note()], lastCursor2='page1')), blob('原作者正文'))
        c = self.client(op)
        result = c.read('sample')
        self.assertEqual(result['text'], '原作者正文')
        self.assertEqual(result['coverage'], 'saved_clipping_version')
        self.assertNotIn('Signature', json.dumps(result))
        self.assertEqual(len(op.calls), 3)
        self.assertEqual(json.loads(op.calls[1].data)['lastCursor2'], '')
        self.assertIn('Authorization', op.calls[0].headers)
        self.assertNotIn('Authorization', op.calls[-1].headers)
        self.assertEqual(sum(r.get_method() == 'GET' for r in op.calls), 1)
        self.assertEqual(c.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)

    def test_pagination_is_bound_to_content_hash(self):
        text = '正文' * 7000
        op = Opener(blob(text), blob(text), blob(text + '修订'))
        c = self.client(op);self.seed(c)
        first = c.read('sample')
        self.assertEqual(len(first['text']), 12000)
        self.assertEqual(first['next_offset'], 12000)
        second = c.read('sample', offset=first['next_offset'], expected_hash=first['content_hash'])
        self.assertEqual(first['text'] + second['text'], text)
        self.assertIsNone(second['next_offset'])
        with self.assertRaisesRegex(w.FullTextError, 'version_changed'):
            c.read('sample', offset=12000, expected_hash=first['content_hash'])

    def test_partial_metadata_scan_resumes_without_restarting_or_fetching_wrong_body(self):
        op = Opener(api(dict(lastCursor2='init', gapTime=5)),
                    api(dict(notes=[note('other')], lastCursor2='page1')),
                    api(dict(notes=[note()], lastCursor2='page2')), blob('目标正文'))
        c = self.client(op)
        first = c.read('sample', max_pages=1)
        self.assertEqual(first['status'], 'lookup_incomplete')
        self.assertNotIn('text', first)
        second = c.read('sample', max_pages=1)
        self.assertEqual(second['text'], '目标正文')
        self.assertEqual(json.loads(op.calls[2].data)['lastCursor2'], 'page1')
        self.assertEqual(sum('/init?' in r.full_url for r in op.calls), 1)

    def test_terminal_null_with_explicit_cursor_is_complete_and_ack_is_not_article_write(self):
        op = Opener(api(dict(lastCursor2='init')), api(dict(notes=None, lastCursor2='end')), api())
        c = self.client(op)
        result = c.read('missing')
        self.assertEqual(result['status'], 'not_in_sync_export')
        self.assertTrue(result['export_complete'])
        self.assertTrue(op.calls[-1].full_url.startswith(w.BASE + 'ack?'))
        self.assertNotIn('text', result)

    def test_expired_signed_url_restarts_metadata_from_empty_cursor(self):
        op = Opener(api(dict(lastCursor2='already-acknowledged')),
                    api(dict(notes=[note()], lastCursor2='fresh-page')), blob('更新正文'))
        c = self.client(op)
        self.seed(c, {'sample': dict(title='旧文章', url='', sou=HOST.replace('2000', '900'), observed_at=900)})
        self.assertEqual(c.read('sample')['text'], '更新正文')
        self.assertEqual(json.loads(op.calls[1].data)['lastCursor2'], '')

    def test_no_clipping_does_not_fabricate_text_or_fetch_source_website(self):
        op = Opener();c = self.client(op)
        self.seed(c, {'sample': dict(title='元数据', url='https://example.test', sou='', observed_at=1000)})
        result = c.read('sample')
        self.assertEqual(result['status'], 'saved_clipping_unavailable')
        self.assertNotIn('text', result)
        self.assertEqual(op.calls, [])

    def test_only_verified_storage_host_https_and_no_embedded_credentials(self):
        for url in ['http://ps1wcbj.oss-cn-beijing.aliyuncs.com/x', 'https://evil.example/x',
                    'https://user:password@ps1wcbj.oss-cn-beijing.aliyuncs.com/x',
                    'https://ps1wcbj.oss-cn-beijing.aliyuncs.com:8443/x']:
            with self.subTest(url=url):
                op = Opener();c = self.client(op)
                self.seed(c, {'sample': dict(title='合成', url='', sou=url, observed_at=1000)})
                with self.assertRaisesRegex(w.FullTextError, 'unapproved_download_host'):
                    c.read('sample')
                self.assertEqual(op.calls, [])

    def test_http_failure_no_retry_or_raw_error_leak(self):
        op = Opener(HTTPError(HOST, 403, 'private upstream diagnostic', {}, None))
        c = self.client(op);self.seed(c)
        with self.assertRaisesRegex(w.FullTextError, '^wucai_fulltext_http_403$'):
            c.read('sample')
        self.assertEqual(len(op.calls), 1)

    def test_errors_and_oversized_response_are_bounded(self):
        for raw, message in [(api({}, code=10010), 'api_error_10010'),
                             (b'x' * (w.MAX_RESPONSE + 1), 'response_too_large')]:
            with self.subTest(message=message):
                op = Opener(raw);c = self.client(op)
                with self.assertRaisesRegex(w.FullTextError, message):
                    c.request('init', {})
                self.assertEqual(len(op.calls), 1)

    def test_missing_cursor_is_not_successful_end_and_unknown_operations_denied(self):
        op = Opener(api(dict(lastCursor2='init')), api(dict(notes=None)))
        c = self.client(op)
        with self.assertRaisesRegex(w.FullTextError, 'invalid_export'):
            c.read('sample')
        with self.assertRaisesRegex(w.FullTextError, 'operation_denied'):
            c.request('delete', {})

    def test_rejects_invalid_input_without_network_and_symlink_cache(self):
        op = Opener();c = self.client(op)
        for kwargs in [dict(note_idx='../secret'), dict(note_idx='sample', offset=True),
                       dict(note_idx='sample', offset=1), dict(note_idx='sample', refresh='yes')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(w.FullTextError):
                c.read(**kwargs)
        self.assertEqual(op.calls, [])
        other = self.root / 'other';other.mkdir()
        link = self.root / 'link';link.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(w.FullTextError, 'symlink_denied'):
            w.Clippings('synthetic', link)

    def test_changed_credential_cannot_reuse_another_accounts_metadata(self):
        op = Opener(api(dict(lastCursor2='init')), api(dict(notes=[note()], lastCursor2='fresh')), blob('当前账号正文'))
        old = self.client(Opener(), token='old-synthetic-token');self.seed(old)
        current = self.client(op, token='new-synthetic-token')
        self.assertEqual(current.read('sample')['text'], '当前账号正文')
        self.assertTrue(op.calls[0].full_url.startswith(w.BASE + 'init?'))

    def test_pending_export_is_polled_on_next_explicit_call_not_mistaken_for_empty(self):
        op = Opener(api(dict(lastCursor2='init', taskStatus='PENDING')),
                    api(dict(lastCursor2='init', taskStatus='SYNCING')),
                    api(dict(notes=[note()], lastCursor2='ready')), blob('已准备正文'))
        c = self.client(op)
        self.assertEqual(c.read('sample')['status'], 'lookup_incomplete')
        self.assertEqual(len(op.calls), 1)
        self.assertEqual(c.read('sample')['text'], '已准备正文')
        self.assertEqual(json.loads(op.calls[1].data)['noteDirDeleted'], False)

    def test_stale_target_during_partial_scan_refreshes_instead_of_reusing_expired_url(self):
        op = Opener(api(dict(lastCursor2='init')), api(dict(notes=[note()], lastCursor2='fresh')), blob('新正文'))
        c = self.client(op)
        state = dict(binding=c.binding, entries={'sample': dict(title='旧', url='', sou=HOST.replace('2000', '900'), observed_at=900)}, cursor='partial', scanning=True, gap=5)
        w.save(c.path, state)
        self.assertEqual(c.read('sample')['text'], '新正文')
        self.assertTrue(op.calls[0].full_url.startswith(w.BASE + 'init?'))

    def test_exact_url_lookup_does_not_need_ai_article_details(self):
        op = Opener(api(dict(lastCursor2='init')), api(dict(notes=[note()], lastCursor2='page')), blob('正确正文'))
        r = self.client(op).read(url='https://example.test/article')
        self.assertEqual(r['text'], '正确正文')
        self.assertEqual(r['note_idx'], 'sample')

    def test_progress_returns_distinct_bound_continuation_and_rejects_stale_cursor(self):
        op = Opener(api(dict(lastCursor2='init')),
                    api(dict(notes=[note('one')], lastCursor2='page1')),
                    api(dict(notes=[note('two')], lastCursor2='page2')))
        c = self.client(op)
        first = c.read('missing', max_pages=1)
        second = c.read(max_pages=1, **first['next_arguments'])
        self.assertNotEqual(first['next_arguments']['lookup_cursor'], second['next_arguments']['lookup_cursor'])
        self.assertFalse(second['can_summarize'])
        with self.assertRaisesRegex(w.FullTextError, 'lookup_cursor_stale'):
            c.read(max_pages=1, **first['next_arguments'])
        self.assertEqual(len(op.calls), 3)

    def test_known_article_refreshes_its_metadata_page_without_restarting_scan(self):
        op = Opener(api(dict(notes=[note()], lastCursor2='old-page-end')), blob('刷新正文'))
        c = self.client(op)
        self.seed(c, {'sample': dict(title='旧', url='', sou=HOST.replace('2000','900'), observed_at=900, page_cursor='page-before-target')})
        self.assertEqual(c.read('sample')['text'], '刷新正文')
        self.assertEqual(json.loads(op.calls[0].data)['lastCursor2'], 'page-before-target')
        self.assertNotIn('/init?', op.calls[0].full_url)
        self.assertEqual(json.loads(c.path.read_text())['cursor'], 'cursor')

    def test_wechat_identity_preserves_case_and_rejects_other_article(self):
        self.assertFalse(w.same_article_url('https://mp.weixin.qq.com/s/AbC','https://mp.weixin.qq.com/s/abc'))
        first='https://mp.weixin.qq.com/s?__biz=one&mid=2&idx=1&sn=hash&scene=1#rd'
        self.assertTrue(w.same_article_url(first, 'https://mp.weixin.qq.com/s?scene=2&sn=hash&idx=1&mid=2&__biz=one'))
        self.assertFalse(w.same_article_url(first, first.replace('sn=hash','sn=other')))

    def test_official_wucai_link_reads_existing_id_without_visiting_webpage(self):
        op=Opener(blob('五彩正文'));c=self.client(op);self.seed(c)
        result=c.read(url='https://marker.dotalk.cn/#/?noteidx=sample')
        self.assertEqual(result['text'],'五彩正文')
        self.assertEqual(result['identity_match'],'wucai_link_id')
        self.assertEqual(len(op.calls),1)

    def test_only_explicit_owner_alias_can_match_short_link_to_id(self):
        op=Opener(blob('确认的原文'));c=self.client(op);self.seed(c)
        c.aliases={'https://mp.weixin.qq.com/s/AbC':'sample'}
        r=c.read(url='https://mp.weixin.qq.com/s/AbC')
        self.assertEqual(r['identity_match'],'owner_confirmed_alias')
        self.assertEqual(r['text'],'确认的原文')
        self.assertNotIn('https://mp.weixin.qq.com/s/abc',c.aliases)


if __name__ == '__main__':
    unittest.main()

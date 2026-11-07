import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis import wucai_cli as w


class ArgumentsTests(unittest.TestCase):
    def test_exact_url_search_and_cursor(self):
        self.assertIn('--url=https://example.test/t/7', w.arguments('get-article', {'url': 'https://example.test/t/7'}))
        self.assertIn('--query=--help', w.arguments('search-articles', {'query': '--help'}))
        self.assertIn('--cursor=next', w.arguments('search-highlights', {'query': '合成', 'cursor': 'next'}))
        self.assertIn('--with-highlights', w.arguments('list-articles', {'with_highlights': True}))

    def test_reject_mutations_options_and_ambiguous_target(self):
        for op, args in [('trash', {'note_idx': '7'}), ('append-diary', {'content': 'x'}),
                         ('search-articles', {'query': 'x', 'output': 'text'}),
                         ('get-article', {}), ('get-article', {'url': 'https://example.test', 'note_idx': '7'}),
                         ('get-article', {'url': 'file:///private'}),
                         ('get-article', {'url': 'https://user:secret@example.test'}),
                         ('list-articles', {'page_size': True}), ('list-articles', {'page_size': 31})]:
            with self.subTest(op=op, args=args), self.assertRaises(ValueError):
                w.arguments(op, args)

    def test_historical_range_and_fourteen_day_boundary(self):
        for span in ['2025-01-01', '2026-10-01:2026-10-14', '14d']:
            self.assertIn('--range=' + span, w.arguments('list-highlights', {'range': span}))
        for span in ['2026-10-01:2026-10-15', '2026-10-14:2026-10-01', '2026-02-30', '99d']:
            with self.assertRaisesRegex(ValueError, '14_days'):
                w.arguments('list-articles', {'range': span})


class ReadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.private = Path(self.tmp.name) / 'private.json'
        self.private.write_text(json.dumps({'region': 'cn', 'api_token': 'wct-synthetic-only'}))
        self.private.chmod(0o600)

    def fake(self, data, *, returncode=0):
        class Process:
            def __init__(self):
                self.returncode = None
                self.stdout = asyncio.StreamReader()
                raw = json.dumps(data, ensure_ascii=False).encode()
                self.stdout.feed_data(raw[:10])
                self.stdout.feed_data(raw[10:])
                self.stdout.feed_eof()
            async def wait(self):
                self.returncode = returncode
            def kill(self):
                self.returncode = -9
        async def create(*args, **kwargs):
            self.assertNotIn('wct-synthetic-only', str(args))
            self.assertEqual(kwargs['env']['WUCAI_REGION'], 'cn')
            self.assertEqual(kwargs['env']['WUCAI_API_TOKEN'], 'wct-synthetic-only')
            return Process()
        return create

    async def test_success_has_live_provenance_and_exact_source(self):
        data = {'code': 1, 'data': {'title': '合成文章', 'url': 'https://example.test/t/7', 'highlights': ['合成划线']}}
        with patch.object(w.asyncio, 'create_subprocess_exec', self.fake(data)):
            result = json.loads(await w.read('get-article', '{"url":"https://example.test/t/7"}', private=self.private))
        self.assertEqual(result['access'], 'live_cli')
        self.assertEqual(result['data'], data)
        self.assertIn('不等于文章全文', result['notice'])

    async def test_api_error_and_secret_are_not_returned_as_source(self):
        for data, expected in [({'code': 10010, 'message': 'private upstream error'}, 'wucai_api_error_10010'),
                               ({'code': 1, 'data': 'wct-synthetic-only'}, 'wucai_response_contains_credential')]:
            with patch.object(w.asyncio, 'create_subprocess_exec', self.fake(data)):
                self.assertEqual(await w.read('list-articles', private=self.private), expected)

    async def test_clipped_flag_does_not_claim_article_full_text(self):
        data = {'code': 1, 'data': {'detail': {'page_title': '合成剪藏', 'is_clipped': True,
                                             'page_note': '', 'highlights': None}}}
        with patch.object(w.asyncio, 'create_subprocess_exec', self.fake(data)):
            result = json.loads(await w.read('get-article', '{"note_idx":"synthetic"}', private=self.private))
        self.assertEqual(result['content_scope']['returned_highlights'], 0)
        self.assertFalse(result['content_scope']['page_note_available'])
        self.assertEqual(result['content_scope']['full_text'], 'not_returned_by_get_article_details')

    async def test_permissions_and_write_denial_precede_process(self):
        with patch.object(w.asyncio, 'create_subprocess_exec') as create:
            self.assertEqual(await w.read('trash', private=self.private), 'wucai_read_only_operation_required')
            self.private.chmod(0o644)
            self.assertEqual(await w.read('list-articles', private=self.private), 'wucai_private_credentials_required')
            create.assert_not_called()

    async def test_large_output_is_bounded_and_process_stopped(self):
        with patch.object(w.asyncio, 'create_subprocess_exec', self.fake({'code': 1, 'data': 'x' * w.MAX_OUTPUT})):
            self.assertEqual(await w.read('list-articles', private=self.private), 'wucai_output_too_large_narrow_query')

    async def test_saved_clipping_uses_separate_reader_and_validates_before_network(self):
        with patch('personal_asis.wucai_fulltext.read_saved', return_value={'status': 'ok', 'text': '原文'}) as fulltext:
            result = json.loads(await w.read('get-article-text', '{"note_idx":"sample"}', private=self.private))
            self.assertEqual(result['text'], '原文')
            fulltext.assert_called_once_with('sample', offset=0, refresh=False, expected_hash='', lookup_cursor='')
            fulltext.reset_mock()
            for args in ['{}', '{"note_idx":"sample","offset":true}', '{"note_idx":"sample","offset":12}',
                         '{"note_idx":"sample","path":"/private"}', '{"url":"file:///private"}']:
                result = await w.read('get-article-text', args, private=self.private)
                self.assertTrue(result.startswith('wucai_'))
            fulltext.assert_not_called()

    async def test_null_detail_does_not_prevent_exact_export_lookup(self):
        with patch.object(w.asyncio, 'create_subprocess_exec', self.fake({'code': 1, 'data': {'detail': None}})), \
             patch('personal_asis.wucai_fulltext.read_saved', return_value={'status': 'lookup_incomplete'}) as fulltext:
            result = json.loads(await w.read('get-article-text', '{"url":"https://example.test/a"}', private=self.private))
            self.assertEqual(result['status'], 'lookup_incomplete')
            fulltext.assert_called_once_with(url='https://example.test/a', offset=0, refresh=False, expected_hash='', lookup_cursor='')

    async def test_metadata_continuation_does_not_repeat_live_url_resolution(self):
        with patch.object(w.asyncio, 'create_subprocess_exec') as create, \
             patch('personal_asis.wucai_fulltext.read_saved', return_value={'status': 'lookup_incomplete'}):
            await w.read('get-article-text', json.dumps({'url':'https://example.test/a', 'lookup_cursor':'a' * 64}), private=self.private)
            create.assert_not_called()

    async def test_saved_clipping_url_must_resolve_to_exact_article(self):
        data = {'code': 1, 'data': {'detail': {'note_idx': 'sample', 'page_url': 'https://example.test/t/7'}}}
        with patch.object(w.asyncio, 'create_subprocess_exec', self.fake(data)), \
             patch('personal_asis.wucai_fulltext.read_saved', return_value={'status': 'ok'}) as fulltext:
            self.assertEqual(json.loads(await w.read('get-article-text', '{"url":"https://example.test/t/7"}', private=self.private))['status'], 'ok')
            fulltext.assert_called_once()
            fulltext.reset_mock()
            result = await w.read('get-article-text', '{"url":"https://example.test/different"}', private=self.private)
            self.assertEqual(result, 'wucai_fulltext_exact_article_required')
            fulltext.assert_not_called()


if __name__ == '__main__':
    unittest.main()

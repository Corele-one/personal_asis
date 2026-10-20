from dataclasses import replace
from datetime import date
import io
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from personal_asis.config import load_config, load_pa1_config
from personal_asis.index import Index
from personal_asis.reading import (ReadingCache, cache_metadata, clean, classify, configure,
                                   fetch, refresh_index, root_for, sync, windows)
from personal_asis.reading_sources import Article, Folo, Page, SourceError, Wucai
from personal_asis.retrieval import retrieve


class Key:
    def get(self):
        return 'wct-SYNTHETIC_ONLY_DO_NOT_USE'


def article(item_id='one', **kwargs):
    return Article(item_id, 'Synthetic cache study', 'https://example.org/cache',
                   author_text='cache invalidation removes stale evidence',
                   content_kind='feed_content', **kwargs)


class Pages:
    def __init__(self, pages):
        self.pages, self.calls = list(pages), []

    def page(self, *args):
        self.calls.append(args)
        result = self.pages.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class ReadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        configure(self.home, 'folo')

    def store(self, item=None, selected=False, now=None):
        with ReadingCache(self.home, 'folo', clock=lambda: now or time.time()) as cache:
            cache.put(item or article(), 'selections' if selected else 'subscriptions')
            return dict(cache.db.execute('SELECT * FROM items').fetchone())

    def results(self, provider=None):
        with Index(self.home / 'index.sqlite3', load_pa1_config(self.home)) as index:
            return retrieve(index, 'cache', provider=provider)

    def test_local_index_unclassified_and_no_implicit_cloud_or_remote_grant(self):
        self.store()
        refresh_index(self.home)
        evidence = self.results()['evidence']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['sensitivity'], 'private')
        self.assertEqual(evidence[0]['reading_provenance']['content_kind'], 'feed_content')
        self.assertIn('[作者原文', evidence[0]['excerpt'])
        self.assertFalse(self.results('mimo')['evidence'])
        with Index(self.home / 'index.sqlite3', load_config(self.home / 'sources.yaml')) as index:
            self.assertFalse(index.search('cache', 'pwa')['results'])

    def test_expiry_rejects_preexisting_index_without_waiting_for_cleanup(self):
        row = self.store(now=time.time() - 29 * 86400)
        refresh_index(self.home)
        self.assertTrue(self.results()['evidence'])
        with ReadingCache(self.home, 'folo') as cache, cache.db:
            cache.db.execute('UPDATE items SET expires_at=?', (time.time() - 1,))
        self.assertTrue((root_for(self.home, 'folo') / row['filename']).is_file())
        self.assertFalse(self.results()['evidence'])
        report = clean(self.home, 'folo')
        self.assertEqual(report['expired_removed'], 1)
        self.assertFalse((root_for(self.home, 'folo') / row['filename']).exists())

    def test_personal_selection_retained_and_arrivals_not_overwritten(self):
        row = self.store(selected=True, now=time.time() - 40 * 86400)
        self.assertIsNotNone(cache_metadata(root_for(self.home, 'folo'), row['filename']))
        self.store(selected=False)
        with ReadingCache(self.home, 'folo') as cache:
            self.assertEqual(cache.db.execute('SELECT count(*) FROM arrivals').fetchone()[0], 2)
            self.assertTrue(cache.db.execute('SELECT selected FROM items').fetchone()[0])

    def test_pagination_limit_resume_and_no_duplicate_items(self):
        api = Pages([Page([article()], '2026-10-14T00:00:00Z', True)])
        first = sync(self.home, 'folo', max_pages=1, source_client=api)
        self.assertEqual(first['status'], 'partial')
        api = Pages([Page([article(), replace(article(), item_id='two')], None, False)])
        second = sync(self.home, 'folo', resume=True, source_client=api)
        self.assertEqual(api.calls[0][3], '2026-10-14T00:00:00Z')
        self.assertEqual(second['status'], 'visible_window_exhausted')
        self.assertFalse(second['complete_account_history'])
        with ReadingCache(self.home, 'folo') as cache:
            self.assertEqual(cache.db.execute('SELECT count(*) FROM items').fetchone()[0], 2)

    def test_unknown_pagination_and_nonadvancing_cursor_are_partial(self):
        unknown = sync(self.home, 'folo', source_client=Pages([Page([article()], None, None)]))
        self.assertEqual(unknown['status'], 'partial')
        api = Pages([Page([article()], 'same', True), Page([article()], 'same', True)])
        stuck = sync(self.home, 'folo', source_client=api)
        self.assertEqual(stuck['coverage'][0]['status'], 'cursor_did_not_advance')
        self.assertEqual(len(api.calls), 2)

    def test_page_failure_preserves_checkpoint_and_reports_failure(self):
        api = Pages([Page([article()], 'next', True), SourceError('reading_network_failed')])
        report = sync(self.home, 'folo', source_client=api)
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(self.results()['evidence'])
        later = Pages([Page([], None, False)])
        sync(self.home, 'folo', resume=True, source_client=later)
        self.assertEqual(later.calls[0][3], 'next')

    def test_wucai_backfill_splits_dates_and_resumes_remaining_windows(self):
        configure(self.home, 'wucai', region='cn')
        api = Pages([Page([], None, False)])
        first = sync(self.home, 'wucai', since='2026-09-01', until='2026-10-01',
                     max_pages=1, source_client=api)
        self.assertEqual(first['remaining_windows'], 2)
        later = Pages([Page([], None, False), Page([], None, False)])
        second = sync(self.home, 'wucai', since='2026-09-01', until='2026-10-01',
                      resume=True, source_client=later)
        self.assertEqual(later.calls[0][1:3], ('2026-09-15', '2026-09-28'))
        self.assertEqual(second['status'], 'visible_window_exhausted')

    def test_revoke_clears_files_and_old_evidence_and_cannot_sync(self):
        self.store(selected=True)
        refresh_index(self.home)
        clean(self.home, 'folo', revoke=True)
        self.assertFalse(self.results()['evidence'])
        self.assertFalse(list(root_for(self.home, 'folo').glob('*.md')))
        with self.assertRaisesRegex(SourceError, 'not_enabled'):
            sync(self.home, 'folo', source_client=Pages([]))

    def test_forget_is_local_exclusion_and_blocks_refetch(self):
        self.store()
        refresh_index(self.home)
        clean(self.home, 'folo', item_id='one')
        with ReadingCache(self.home, 'folo') as cache:
            self.assertEqual(cache.put(article(), 'selections'), 'excluded')
        self.assertFalse(self.results()['evidence'])

    def test_local_classification_does_not_grant_model_and_new_version_resets(self):
        self.store()
        classify(self.home, 'folo', 'one', 'normal')
        self.assertEqual(self.results()['evidence'][0]['sensitivity'], 'normal')
        self.assertFalse(self.results('mimo')['evidence'])
        self.store(replace(article(), author_text='cache new evidence'))
        refresh_index(self.home)
        self.assertEqual(self.results()['evidence'][0]['sensitivity'], 'private')

    def test_same_origin_does_not_count_as_independent_evidence(self):
        self.store()
        configure(self.home, 'wucai')
        with ReadingCache(self.home, 'wucai') as cache:
            cache.put(replace(article(), author_text='', highlights=[{'quote': 'cache original', 'note': 'my annotation'}]), 'selections')
        refresh_index(self.home)
        self.assertEqual(len(self.results()['evidence']), 1)

    def test_raw_credentials_are_never_written_and_invalidate_prior_version(self):
        row = self.store()
        dangerous = replace(article(), author_text='authorization: Bearer SYNTHETIC_SECRET_CANARY')
        with ReadingCache(self.home, 'folo') as cache:
            self.assertEqual(cache.put(dangerous, 'subscriptions'), 'credential_excluded')
        self.assertFalse((root_for(self.home, 'folo') / row['filename']).exists())
        for path in self.home.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_SECRET_CANARY', path.read_bytes())

    def test_manifest_or_cached_file_tampering_fails_closed(self):
        row = self.store()
        refresh_index(self.home)
        (root_for(self.home, 'folo') / row['filename']).write_text('cache tampered')
        self.assertFalse(self.results()['evidence'])

    def test_discovery_preserves_fetched_body_and_original_expiry(self):
        row = self.store(now=time.time() - 10 * 86400)
        self.store(replace(article(), author_text='', content_kind='metadata_only'))
        with ReadingCache(self.home, 'folo') as cache:
            current = cache.db.execute('SELECT * FROM items').fetchone()
            self.assertEqual(current['expires_at'], row['expires_at'])
        refresh_index(self.home)
        self.assertIn('stale evidence', self.results()['evidence'][0]['excerpt'])

    def test_cloud_bundle_requires_explicit_file_grant_and_retains_attribution(self):
        from personal_asis.config import root_identity
        from personal_asis.retrieval import ContextBundle
        self.store()
        classify(self.home, 'folo', 'one', 'normal')
        config = load_config(self.home / 'sources.yaml')
        source = config.sources[0]
        filename = next(source.root.glob('*.md')).name
        policy = {'version': 1, 'sources': {source.id: {'root_identity': root_identity(source.root),
                  'model_providers': ['mimo'], 'private_model_providers': [],
                  'model_paths': [filename], 'model_all_files': False}}}
        (self.home / 'pa1-policy.json').write_text(json.dumps(policy))
        evidence = self.results('mimo')['evidence']
        self.assertEqual(len(evidence), 1)
        bundle = ContextBundle('cache', 'mimo', evidence, 'lexical')
        cloud = bundle.cloud_input()['evidence'][0]
        self.assertEqual(cloud['reading_source']['url'], 'https://example.org/cache')
        self.assertIn('[作者原文', cloud['text'])
        bundle.revalidate(self.home)
        clean(self.home, 'folo', revoke=True)
        with self.assertRaisesRegex(ValueError, 'stale'):
            bundle.revalidate(self.home)

    def test_semantic_cache_does_not_encode_link_or_account_metadata(self):
        from personal_asis.semantic import chunks
        row = self.store()
        raw = (root_for(self.home, 'folo') / row['filename']).read_text()
        fragments = list(chunks(raw))
        self.assertTrue(fragments)
        self.assertTrue(all('[作者原文' in fragment for _, fragment in fragments))
        self.assertFalse(any('[原文链接]' in fragment for _, fragment in fragments))

    def test_detail_cannot_replace_another_item(self):
        class Detail:
            def detail(self, item_id):
                return article('other')
        with self.assertRaisesRegex(SourceError, 'identity_mismatch'):
            fetch(self.home, 'folo', 'one', Detail())

    def test_missing_manifest_cannot_be_imported_as_cache(self):
        self.store()
        refresh_index(self.home)
        (root_for(self.home, 'folo').parent / 'manifest.sqlite3').unlink()
        self.assertFalse(self.results()['evidence'])


class ProtocolTests(unittest.TestCase):
    def test_wucai_null_articles_is_terminal_only_with_explicit_empty_cursor(self):
        api = Wucai(store=Key())
        with patch.object(api, 'call', return_value={'articles': None, 'next_cursor': ''}):
            page = api.page('selections', '2026-07-23', '2026-08-05')
        self.assertEqual(page.articles, [])
        self.assertFalse(page.more)
        for value in ({'articles': None}, {'articles': None, 'next_cursor': 'more'},
                      {'articles': None, 'next_cursor': '', 'has_more': True}, {'next_cursor': ''}):
            with self.subTest(value=value), patch.object(api, 'call', return_value=value):
                with self.assertRaises(SourceError):
                    api.page('selections', '2026-07-23', '2026-08-05')

    def test_wucai_live_field_names_nullable_highlights_and_no_invented_fulltext(self):
        row = {'note_idx':'one','page_title':'Observed schema fixture',
               'page_url':'https://example.org/observed','page_note':'User note',
               'highlights':None,'created_at':1728000000,'is_clipped':True}
        item=Wucai.article(row)
        self.assertEqual(item.title,'Observed schema fixture')
        self.assertEqual(item.url,'https://example.org/observed')
        self.assertEqual(item.user_note,'User note')
        self.assertEqual(item.content_kind,'annotations_only')
        self.assertFalse(item.author_text)
        self.assertFalse(item.published_at)  # Database creation is not original publication.
        row['highlights']=[{'h_id':123,'content':'Author quote','annonation':'User annotation',
                            'image_url':'https://example.org/image.png'}]
        item=Wucai.article(row)
        self.assertEqual(item.highlights,[{'quote':'Author quote','note':'User annotation'}])
        self.assertEqual(item.media_urls,['https://example.org/image.png'])

    def test_wucai_live_cursor_only_protocol_and_wrapped_details(self):
        api=Wucai(store=Key())
        row={'note_idx':'one','page_title':'Example','highlights':None}
        with patch.object(api,'call',return_value={'articles':[row],'next_cursor':'opaque-next'}):
            page=api.page('selections','2026-07-05','2026-07-18')
            self.assertTrue(page.more)
            self.assertEqual(page.cursor,'opaque-next')
        with patch.object(api,'call',return_value={'articles':[],'next_cursor':''}):
            self.assertFalse(api.page('selections','2026-07-05','2026-07-18').more)
        with patch.object(api,'call',return_value={'detail':row}):
            self.assertEqual(api.detail('one').item_id,'one')

    def test_wucai_only_read_endpoints_and_redacted_errors(self):
        class Opener:
            def open(self, req, timeout):
                self.request = req
                return io.BytesIO(json.dumps({'code': 10010, 'message': Key().get()}).encode())
        opener = Opener()
        api = Wucai(store=Key(), opener=opener)
        for op in ('trash_article', 'append_diary', 'list_diary', '../set_article_status'):
            with self.assertRaisesRegex(SourceError, 'denied'):
                api.call(op, {})
        with self.assertRaisesRegex(SourceError, '^reading_wucai_code_10010$'):
            api.call('list_articles', {})
        self.assertTrue(opener.request.full_url.startswith('https://api.wucai.site/'))

    def test_wucai_highlights_never_claim_full_text_and_keep_annotations_separate(self):
        item = Wucai.article({'note_idx': 'abc', 'title': 'Example',
                              'content': 'THIS_IS_NOT_A_DOCUMENTED_FULLTEXT_FIELD',
                              'highlights': [{'text': 'author quote', 'note': 'user opinion'}]})
        self.assertEqual(item.content_kind, 'highlights_only')
        self.assertFalse(item.author_text)
        self.assertEqual(item.highlights[0]['note'], 'user opinion')
        with self.assertRaisesRegex(SourceError, 'schema_unverified'):
            Wucai.article({'unsupported_id': 'abc'})

    def test_date_windows_inclusive_max14_days_and_no_reversal(self):
        result = list(windows('2026-01-01', '2026-01-29'))
        self.assertEqual(len(result), 3)
        for start, end in result:
            self.assertLessEqual((date.fromisoformat(end) - date.fromisoformat(start)).days, 13)
        with self.assertRaises(SourceError):
            list(windows('2026-02-01', '2026-01-01'))

    def test_folo_allowlisted_argv_fixed_host_env_token_and_no_mark_read(self):
        seen = []
        def runner(argv, **kwargs):
            seen.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, json.dumps({'ok': True, 'data': {
                'entries': [], 'nextCursor': None, 'hasNext': False}}).encode(), b'')
        api = Folo('/usr/bin/true', Key(), runner)
        api.page('subscriptions', limit=5)
        argv, kwargs = seen[0]
        self.assertEqual(argv[1:5], ['--format', 'json', '--api-url', 'https://api.folo.is'])
        self.assertNotIn(Key().get(), ' '.join(argv))
        self.assertEqual(kwargs['env']['FOLO_TOKEN'], Key().get())
        for operation in ('mark-read', 'login', 'feed refresh', 'collection add'):
            with self.assertRaisesRegex(SourceError, 'denied'):
                api.call(operation)
        self.assertEqual(len(seen), 1)

    def test_folo_metadata_discovery_does_not_archive_subscription_body(self):
        data = {'entries': {'id': '123', 'title': 'A', 'content': '<p>author body</p><script>hidden</script>'}}
        self.assertFalse(Folo.article(data).author_text)
        selected = Folo.article(data, True)
        self.assertEqual(selected.author_text, 'author body')
        self.assertEqual(selected.content_kind, 'feed_content')

    def test_folo_collection_cursor_preserved_and_not_derived_from_publication(self):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, json.dumps({'ok': True, 'data': {
                'entries': [{'entries': {'id': 'one', 'publishedAt': '2000-01-01'}}],
                'nextCursor': '2026-10-15T00:00:00Z', 'hasNext': True}}).encode(), b'')
        page = Folo('/usr/bin/true', Key(), runner).page('selections')
        self.assertEqual(page.cursor, '2026-10-15T00:00:00Z')


if __name__ == '__main__':
    unittest.main()

from dataclasses import replace
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

from personal_asis import reading, reading_library as lib
from personal_asis.reading_sources import Article, Page, SourceError


ACCOUNTS = {('wucai', 'cn'): 'Synthetic WUCAI', ('xiaohongshu', 'default'): 'Primary', ('xiaohongshu', 'second'): 'Secondary'}


def article(item='one', **values):
    return Article(item, '器件仿真与可靠性 Synthetic study', 'https://example.org/' + item, **values)


class ReadingLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.now = 10 * reading.TTL
        self.library = lib.Library(self.home, accounts=ACCOUNTS, clock=lambda: self.now)
        self.addCleanup(self.library.close)

    def test_payload_dedup_keeps_account_relations_and_versions_independent(self):
        for account in ('default', 'second'):
            self.library.put('xiaohongshu', account, article(), 'favorite')
        self.assertEqual(self.library.status()['unique_payloads'], 1)
        self.assertEqual(len(self.library.search('器件')), 2)
        self.assertEqual(len(self.library.search('可靠性', account='second')), 1)
        self.library.put('xiaohongshu', 'second', article(author_text='Second account visible version', content_kind='note_text'))
        self.assertEqual(self.library.read('xiaohongshu', 'default', 'one')['content']['content_kind'], 'metadata_only')
        self.assertEqual(len(self.library.search('Second account', account='default')), 0)
        self.assertEqual(len(self.library.search('Second account', account='second')), 1)

    def test_repeat_list_does_not_erase_body_or_fabricate_collection_time(self):
        item = article(author_text='Full body synthetic evidence', content_kind='note_text')
        self.library.put('xiaohongshu', 'second', item, 'favorite')
        self.now += 100
        self.library.put('xiaohongshu', 'second', article(), 'favorite')
        result = self.library.read('xiaohongshu', 'second', 'one')
        self.assertEqual(result['content']['author_text'], item.author_text)
        self.assertIsNone(result['relations'][0]['occurred_at'])
        self.assertEqual(result['relations'][0]['last_seen'], self.now)
        self.assertLess(result['fetched_at'], self.now)

    def test_expired_body_is_not_resurrected_by_new_favorite_metadata(self):
        self.library.put('xiaohongshu', 'default', article(author_text='Old expired body', content_kind='note_text'), 'discovery')
        self.now += reading.TTL + 1
        self.assertEqual(self.library.search('expired'), [])
        with self.assertRaises(SourceError):
            self.library.read('xiaohongshu', 'default', 'one')
        self.library.put('xiaohongshu', 'default', article(), 'favorite')
        self.assertEqual(self.library.read('xiaohongshu', 'default', 'one')['content']['content_kind'], 'metadata_only')

    def test_forget_is_scoped_stops_reimport_and_prunes_unreferenced_fts(self):
        for account in ('default', 'second'):
            self.library.put('xiaohongshu', account, article(), 'favorite')
        self.library.forget('xiaohongshu', 'default', 'one')
        self.assertEqual(self.library.put('xiaohongshu', 'default', article(), 'favorite'), 'excluded')
        self.assertEqual(len(self.library.search('器件')), 1)
        self.library.forget('xiaohongshu', 'second', 'one')
        self.assertEqual(self.library.status()['unique_payloads'], 0)
        self.assertEqual(self.library.db.execute('SELECT count(*) FROM library_fts').fetchone()[0], 0)

    def test_disabled_and_unconfigured_accounts_cannot_read_or_search(self):
        self.library.put('xiaohongshu', 'second', article(), 'favorite')
        self.library.db.execute("UPDATE accounts SET enabled=0 WHERE account='second'")
        self.library.db.commit()
        self.assertEqual(self.library.search('器件'), [])
        with self.assertRaises(SourceError):
            self.library.read('xiaohongshu', 'second', 'one')
        self.library.allowed.pop(('xiaohongshu', 'second'))
        self.assertEqual(self.library.search('器件'), [])

    def test_credential_content_invalidates_previous_content_without_persisting_secret(self):
        self.library.put('wucai', 'cn', article(), 'saved_article')
        with self.assertRaises(SourceError):
            self.library.put('wucai', 'cn', article(author_text='Authorization: Bearer sk-' + 'x' * 48, content_kind='note_text'), 'saved_article')
        self.assertEqual(self.library.search('器件'), [])

    def test_private_database_readonly_access_and_concurrent_writer_lock(self):
        self.library.put('wucai', 'cn', article(), 'saved_article')
        self.assertEqual(self.library.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaisesRegex(SourceError, 'busy'):
            lib.Library(self.home, accounts=ACCOUNTS)
        with lib.Library(self.home, readonly=True, accounts=ACCOUNTS) as reader:
            self.assertEqual(len(reader.search('Synthetic')), 1)
        target = self.home / 'linked'
        target.symlink_to(self.home, target_is_directory=True)
        with self.assertRaisesRegex(SourceError, 'symlink'):
            lib.Library(target, accounts=ACCOUNTS)

    def test_wucai_resume_failure_stops_at_failed_page_and_repeated_import_is_idempotent(self):
        api = Mock()
        api.page.side_effect = [Page([article()], 'next', True), SourceError('synthetic_network_failure')]
        with self.assertRaises(SourceError):
            lib.sync_wucai(self.library, '2026-10-01', '2026-10-14', client=api, pause=lambda v: None)
        row = self.library.db.execute('SELECT * FROM coverage').fetchone()
        self.assertEqual(row['cursor'], 'next')
        self.assertEqual(row['status'], 'failed')
        api.page.side_effect = [Page([article(), article('two')], '', False)]
        lib.sync_wucai(self.library, '2026-10-01', '2026-10-14', client=api, pause=lambda v: None)
        self.assertEqual(api.page.call_args.args[3], 'next')
        api.page.reset_mock()
        lib.sync_wucai(self.library, '2026-10-01', '2026-10-14', client=api, pause=lambda v: None)
        api.page.assert_not_called()
        self.assertEqual(len(self.library.search('器件')), 2)

    def test_unknown_or_repeating_pagination_never_claims_window_exhausted(self):
        api = Mock()
        api.page.return_value = Page([article()], None, None)
        lib.sync_wucai(self.library, '2026-10-01', '2026-10-14', client=api, pause=lambda v: None)
        self.assertEqual(self.library.db.execute('SELECT status FROM coverage').fetchone()[0], 'pagination_unverified')
        api.page.return_value = Page([article()], 'stuck', True)
        with self.assertRaisesRegex(SourceError, 'stalled'):
            lib.sync_wucai(self.library, '2026-10-01', '2026-10-14', client=api, pause=lambda v: None)

    def test_xhs_visible_page_does_not_imply_full_history_or_remove_missing_favorites(self):
        api = Mock()
        api.page.return_value = Page([article(), article('two')], None, None)
        lib.sync_xhs(self.library, 'second', client=api)
        api.page.return_value = Page([article('two')], None, None)
        result = lib.sync_xhs(self.library, 'second', client=api)
        self.assertEqual(result['status'], 'visible_page_only')
        self.assertEqual(len(self.library.search('器件', account='second')), 2)
        self.assertFalse(self.library.status()['complete_account_history'])

    def test_fetch_keeps_relation_times_and_checks_identity(self):
        self.library.put('xiaohongshu', 'second', article(), 'favorite')
        self.now += 100
        api = Mock()
        api.detail.return_value = article(author_text='Fetched full body', content_kind='note_text')
        lib.fetch(self.library, 'xiaohongshu', 'second', 'one', client=api)
        row = self.library.read('xiaohongshu', 'second', 'one')
        self.assertEqual(row['fetched_at'], self.now)
        self.assertLess(row['relations'][0]['last_seen'], self.now)
        api.detail.return_value = article('other')
        with self.assertRaisesRegex(SourceError, 'identity'):
            lib.fetch(self.library, 'xiaohongshu', 'second', 'one', client=api)

    def test_legacy_migration_keeps_attribution_and_tombstones(self):
        reading.configure(self.home, 'wucai', region='cn')
        with reading.ReadingCache(self.home, 'wucai', clock=lambda: self.now) as cache:
            item = article('legacy', user_note='My page note', highlights=[{'quote': 'Author quotation', 'note': 'My annotation'}], content_kind='highlights_only')
            cache.put(item, 'selections')
            cache.put(article('forgotten'), 'selections')
            cache.forget('forgotten')
        lib.import_legacy(self.library)
        row = self.library.read('wucai', 'cn', 'legacy')
        self.assertEqual(row['content']['user_note'], 'My page note')
        self.assertTrue(any(p['note'] == 'My annotation' for p in row['content']['highlights']))
        self.assertEqual(self.library.put('wucai', 'cn', article('forgotten'), 'saved_article'), 'excluded')

    def test_xhs_client_uses_account_specific_keychain_and_page_token_namespaces(self):
        with patch.object(lib, 'xhs_configurations', return_value={'second': {'endpoint': 'http://127.0.0.1:18061/mcp'}}), patch('personal_asis.credentials.CredentialStore') as store:
            client = lib.xhs_client(self.home, 'second')
            client.access_store('note')
        self.assertEqual(store.call_args_list[0].args[0], 'xiaohongshu-mcp:second')
        self.assertEqual(store.call_args_list[1].args[0], 'library:second:note')


if __name__ == '__main__':
    unittest.main()

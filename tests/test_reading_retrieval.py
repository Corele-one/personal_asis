import json
from pathlib import Path
import tempfile
import unittest

from personal_asis import reading
from personal_asis.reading_sources import Article
from personal_asis.reading_retrieval import snapshot
from personal_asis.retrieval_channel import snapshot as channel_snapshot
from personal_asis.retrieval_v2 import ContextBundleV2


class Detail:
    def __init__(self, kind='feed_content'):
        self.calls = []
        self.kind = kind
    def detail(self, item_id):
        self.calls.append(item_id)
        return Article(item_id, 'Synthetic body', 'https://example.org/article', author='External Author',
            author_text='cache coherence is an external author claim',
            highlights=[{'quote':'cache highlight by owner','note':'cache annotation by owner'}], content_kind=self.kind)


class ReadingRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        reading.configure(self.home, 'folo')

    def policy(self, remote=False, model=False):
        path = self.home / 'sources.yaml'
        data = json.loads(path.read_text())
        data['sources'][0].update(remote_metadata=remote, private_remote_metadata=remote,
                                 remote_evidence=remote, private_remote_evidence=remote,
                                 model_providers=['mimo'] if model else [], model_all_files=model,
                                 private_model_providers=['mimo'] if model else [])
        path.write_text(json.dumps(data))

    def test_explicit_account_fetch_returns_body_chunks_with_independent_attribution(self):
        api = Detail()
        value = snapshot(self.home, 'folo', 'one', 'cache', fetch_body=True, source_client=api)
        self.assertEqual(api.calls, ['one'])
        self.assertEqual(value['model_calls'], 0)
        self.assertEqual(value['platform_mutations'], 0)
        self.assertEqual({e['attribution_actor'] for e in value['evidence']}, {'original_author', 'owner_annotation'})
        self.assertTrue(all(e['content_completeness'] == 'partial' for e in value['evidence']))
        self.assertFalse(value['coverage']['complete_article_verified'])

    def test_missing_model_or_channel_permission_never_granted_by_fetch(self):
        snapshot(self.home, 'folo', 'one', 'cache', fetch_body=True, source_client=Detail())
        for options in [{'provider': 'mimo'}, {'channel': 'feishu'}]:
            value = snapshot(self.home, 'folo', 'one', 'cache', **options)
            self.assertEqual(value['evidence'], [])
        self.assertEqual(snapshot(self.home, 'folo', 'one', 'cache')['status'], 'ok')

    def test_remote_read_is_independent_from_model_disclosure(self):
        snapshot(self.home, 'folo', 'one', 'cache', fetch_body=True, source_client=Detail())
        self.policy(remote=True)
        value = channel_snapshot(self.home, {'query': 'cache', 'source_ids': ['reading_folo'], 'channel': 'feishu'})
        self.assertTrue(value['evidence'])
        self.assertEqual(value['model_calls'], 0)
        self.assertFalse(snapshot(self.home, 'folo', 'one', 'cache', provider='mimo')['evidence'])

    def test_metadata_only_never_becomes_body(self):
        with reading.ReadingCache(self.home, 'folo') as cache:
            cache.put(Article('meta', 'cache metadata', 'https://example.org/meta', content_kind='metadata_only'), 'subscriptions')
        reading.refresh_index(self.home)
        self.assertEqual(snapshot(self.home, 'folo', 'meta', 'cache')['evidence'], [])

    def test_deleted_revoked_or_expired_account_data_not_returned(self):
        for operation in ['forget', 'expire', 'revoke']:
            with self.subTest(operation=operation):
                reading.configure(self.home, 'folo')
                snapshot(self.home, 'folo', 'one', 'cache', fetch_body=True, source_client=Detail())
                with reading.ReadingCache(self.home, 'folo') as cache:
                    if operation == 'forget': cache.forget('one')
                    elif operation == 'expire': cache.db.execute('UPDATE items SET expires_at=0'); cache.db.commit()
                    else: cache.db.execute("UPDATE meta SET value='0' WHERE key='enabled'"); cache.db.commit()
                self.assertFalse(snapshot(self.home, 'folo', 'one', 'cache')['evidence'])

    def test_excluded_connector_or_invalid_query_rejected_before_fetch(self):
        api = Detail()
        for connector in ['zhihu', 'wechat']:
            with self.assertRaisesRegex(ValueError, 'excluded'):
                snapshot(self.home, connector, 'one', 'cache', fetch_body=True, source_client=api)
        with self.assertRaises(ValueError):
            snapshot(self.home, 'folo', 'one', '', fetch_body=True, source_client=api)
        self.assertEqual(api.calls, [])

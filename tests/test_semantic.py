import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from personal_asis.config import load_config
from personal_asis.index import Index
from personal_asis.pa1 import configure, fixture, settings
from personal_asis.retrieval import build_bundle, context_excerpt, retrieve
from personal_asis.semantic import chunks


class CountingEncoder:
    cache_key = 'synthetic-encoder-v1'

    def __init__(self):
        self.seen = []

    def encode_query(self, query):
        return [1., 0.]

    def encode_documents(self, texts):
        self.seen.extend(texts)
        return [[1., 0.] if 'coherence' in text or 'TAIL_EVIDENCE' in text
                else [0.1, 1.] for text in texts]


class SemanticTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = fixture(self.tmp.name)
        configure(self.home)
        self.encoder = CountingEncoder()

    def retrieve(self, provider='mimo', encoder=None):
        with Index(self.home/'index.sqlite3', load_config(self.home/'sources.yaml')) as index:
            return retrieve(index, 'meaning', provider=provider, encoder=encoder or self.encoder)

    def update_source(self, edit):
        data = json.loads((self.home/'sources.yaml').read_text())
        edit(data['sources'][0])
        (self.home/'sources.yaml').write_text(json.dumps(data))

    def reconcile(self):
        with Index(self.home/'index.sqlite3', load_config(self.home/'sources.yaml')) as index:
            index.reconcile()

    def cached(self):
        with closing(sqlite3.connect(self.home/'semantic.sqlite3')) as db:
            return db.execute('SELECT scope,model,document,content_hash,vector FROM vectors').fetchall()

    def test_warm_cache_survives_encoder_restart_and_never_encodes_denied_text(self):
        cold = self.retrieve()
        self.assertEqual(cold['vector_cache']['encoded'], 2)
        self.assertFalse(any('CANARY' in text for text in self.encoder.seen))
        other = CountingEncoder()
        warm = self.retrieve(encoder=other)
        self.assertEqual(warm['vector_cache']['hits'], 2)
        self.assertEqual(warm['vector_cache']['encoded'], 0)
        self.assertEqual(other.seen, [])
        self.assertEqual(cold['evidence'], warm['evidence'])
        self.assertEqual((self.home/'semantic.sqlite3').stat().st_mode & 0o777, 0o600)

    def test_modified_and_deleted_sources_purge_stale_vectors_even_before_reconcile(self):
        initial = self.retrieve()
        old_hash = next(e['content_hash'] for e in initial['evidence'] if e['path_hint']=='cache.md')
        (self.home/'source/cache.md').write_text('# cache\nnew synthetic body\n')
        (self.home/'source/coherence.md').unlink()
        self.assertEqual(self.retrieve()['evidence'], [])
        self.assertEqual(self.cached(), [])
        self.reconcile()
        result = self.retrieve()
        self.assertEqual(result['vector_cache']['encoded'], 1)
        self.assertNotEqual(result['evidence'][0]['content_hash'], old_hash)

    def test_revoked_permissions_and_disabled_source_prune_provider_cache(self):
        self.retrieve()
        self.update_source(lambda s:s.update(model_paths=['coherence.md']))
        self.assertEqual(len(self.retrieve()['evidence']), 1)
        self.assertEqual(len(self.cached()), 1)
        self.update_source(lambda s:s.update(index=False))
        self.assertEqual(self.retrieve()['evidence'], [])
        self.assertEqual(self.cached(), [])

    def test_private_reclassification_cannot_reuse_authorized_vectors(self):
        self.retrieve()
        (self.home/'source/cache.md').write_text('---\nsensitivity: private\n---\ncache CANARY\n')
        self.reconcile()
        result = self.retrieve()
        self.assertEqual([e['path_hint'] for e in result['evidence']], ['coherence.md'])
        self.assertEqual(len(self.cached()), 1)

    def test_model_change_reencodes_instead_of_reusing_vectors(self):
        self.retrieve()
        self.encoder.cache_key = 'synthetic-encoder-v2'
        result = self.retrieve()
        self.assertEqual(result['vector_cache']['hits'], 0)
        self.assertEqual(result['vector_cache']['encoded'], 2)
        self.assertEqual({row[1] for row in self.cached()}, {'synthetic-encoder-v2'})

    def test_provider_scope_cannot_reuse_local_private_cache(self):
        local = self.retrieve(provider=None)
        self.assertEqual(local['vector_cache']['encoded'], 4)
        self.encoder.seen.clear()
        model = self.retrieve()
        self.assertEqual(model['vector_cache']['hits'], 0)
        self.assertEqual(model['vector_cache']['encoded'], 2)
        self.assertFalse(any('CANARY' in text for text in self.encoder.seen))

    def test_invalid_cached_vector_is_rebuilt(self):
        self.retrieve()
        with closing(sqlite3.connect(self.home/'semantic.sqlite3')) as db, db:
            db.execute("UPDATE vectors SET vector='[NaN, 0]'")
        result = self.retrieve()
        self.assertEqual(result['vector_cache']['encoded'], 2)
        self.assertEqual(result['mode'], 'hybrid_semantic')

    def test_backend_and_malformed_vector_failures_keep_lexical_retrieval(self):
        for failure in ('runtime', 'count', 'nan', 'zero', 'dimension'):
            class Broken:
                def encode(self, texts):
                    if failure == 'runtime':
                        raise RuntimeError('synthetic inference failure')
                    if failure == 'count':
                        return []
                    if len(texts) == 1 and texts[0] == 'cache':
                        return [[1., 0.]]
                    return {'nan':[[float('nan'),0.]]*len(texts),
                            'zero':[[0.,0.]]*len(texts),
                            'dimension':[[1.,0.,0.]]*len(texts)}[failure]
            with self.subTest(failure=failure), Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
                result=retrieve(index, 'cache', provider='mimo', encoder=Broken())
                self.assertEqual(result['mode'], 'lexical')
                self.assertFalse(result['semantic_enabled'])
                self.assertTrue(result['degradation'])
                self.assertEqual(len(result['evidence']), 2)

    def test_corrupt_cache_falls_back_without_losing_lexical_results(self):
        (self.home/'semantic.sqlite3').write_bytes(b'synthetic invalid database')
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            result=retrieve(index, 'cache', provider='mimo', encoder=self.encoder)
        self.assertEqual(result['mode'], 'lexical')
        self.assertEqual(len(result['evidence']), 2)

    def test_long_document_semantic_window_yields_exact_revalidatable_tail_excerpt(self):
        text = '# cache\n\n' + ('unrelated filler ' * 900) + 'TAIL_EVIDENCE coherence keeps replicas consistent.\n'
        (self.home/'source/cache.md').write_text(text)
        self.reconcile()
        bundle=build_bundle(self.home, 'meaning', encoder=self.encoder)
        evidence=next(e for e in bundle.evidence if e['path_hint']=='cache.md')
        self.assertIn('TAIL_EVIDENCE',evidence['excerpt'])
        self.assertGreater(evidence['column_start'], 12000)
        bundle.revalidate(self.home)
        self.assertTrue(all(len(t)<=400 for t in self.encoder.seen))

    def test_windows_cover_body_skip_frontmatter_and_map_crlf_offsets(self):
        text='---\r\ninternal: hidden\r\n---\r\n# title\r\n\r\n'+('a'*470)+' known body\r\n'
        windows=list(chunks(text))
        self.assertTrue(all('internal' not in t for _,t in windows))
        covered=set(i for start,t in windows for i in range(start,start+len(t)))
        self.assertTrue(all(i in covered or text[i].isspace() for i in range(text.index('a'*470),len(text))))
        selected=context_excerpt(text,'known',window=(windows[-1][0],len(text)))
        line=text.splitlines()[selected['line_start']-1]
        self.assertEqual(line[selected['column_start']-1:selected['column_start']-1+len(selected['excerpt'])],selected['excerpt'])

    def test_semantic_configuration_can_be_enabled_and_disabled_without_cloud_enable(self):
        data=configure(self.home,semantic_model_dir=self.home,
                       semantic_query_prefix='query: ',semantic_document_prefix='passage: ')
        self.assertFalse(data['enabled'])
        self.assertTrue(data['synthetic_only'])
        self.assertEqual(settings(self.home)['semantic_query_prefix'], 'query: ')
        self.assertIsNone(configure(self.home,disable_semantic=True)['semantic_model_dir'])

    def test_source_filter_keeps_independent_warm_cache_and_rejects_unknown_sources(self):
        self.retrieve()
        with Index(self.home/'index.sqlite3',load_config(self.home/'sources.yaml')) as index:
            result=retrieve(index,'meaning',provider='mimo',encoder=self.encoder,source_ids=['synthetic'])
            self.assertEqual(result['vector_cache']['encoded'],2)
            with self.assertRaisesRegex(ValueError,'known_source_ids'):
                retrieve(index,'meaning',source_ids=['unknown'])
        self.assertEqual(self.retrieve()['vector_cache']['hits'],2)

    def test_bundle_rejects_tampered_private_label_or_original_link(self):
        bundle=build_bundle(self.home,'cache',encoder=self.encoder)
        bundle.evidence[0]['sensitivity']='private'
        with self.assertRaisesRegex(ValueError,'identity_or_sensitivity_mismatch'):
            bundle.revalidate(self.home)
        bundle=build_bundle(self.home,'cache',encoder=self.encoder)
        bundle.evidence[0]['original_uri']='file:///synthetic/wrong-file.md'
        with self.assertRaisesRegex(ValueError,'identity_or_sensitivity_mismatch'):
            bundle.revalidate(self.home)

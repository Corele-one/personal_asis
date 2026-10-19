import json
from pathlib import Path
import tempfile
import unittest

from personal_asis.config import load_pa1_config, root_identity
from personal_asis.index import Index
from personal_asis.retrieval_eval import fixture
from personal_asis.retrieval_private_eval import evaluate_private
from personal_asis.retrieval_v2 import RetrievalV2, build_bundle_v2, literal_support


class Scorer:
    cache_key = 'b' * 64
    def score(self, query, passages):
        return [5.] * len(passages)


class QualityContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        fixture(self.home)

    def search(self, query, **kwargs):
        with Index(self.home/'index.sqlite3', load_pa1_config(self.home)) as index, RetrievalV2(index) as v2:
            return v2.search(query, mode='lexical', provider='mimo', **kwargs)

    def test_weak_han_match_does_not_become_evidence_from_a_high_reranker_score(self):
        old = self.search('紫色猎鹰保密实验', reranker=Scorer(), min_score=0.)
        self.assertTrue(old['evidence'])
        new = self.search('紫色猎鹰保密实验', reranker=Scorer(), min_score=0., quality_profile='strict-lexical-v1')
        self.assertEqual(new['protocol'], 'retrieval-v2.3')
        self.assertFalse(new['evidence'])
        self.assertGreater(new['retrieval_policy']['weak_lexical_candidates_removed'], 0)

    def test_identifiers_short_queries_and_exact_anchors_are_preserved(self):
        for query in ('页表转换结果为何放在TLB中', '缓存一致性', '我的批注'):
            result = self.search(query, reranker=Scorer(), min_score=0., quality_profile='strict-lexical-v1')
            self.assertTrue(result['evidence'], query)
        self.assertTrue(literal_support('完全照录的一段中文原始查询', {
            'title': '', 'excerpt': '完全照录的一段中文原始查询'}))

    def test_semantic_only_results_do_not_need_literal_overlap(self):
        class Encoder:
            def encode_query(self, query): return [1., 0.]
            def encode_documents(self, texts): return [[1., 0.] for _ in texts]
        with Index(self.home/'index.sqlite3', load_pa1_config(self.home)) as index, RetrievalV2(index) as v2:
            result = v2.search('没有字面交集的跨语言问题', provider='mimo', mode='semantic',
                encoder=Encoder(), reranker=Scorer(), min_score=0., quality_profile='strict-lexical-v1')
        self.assertTrue(result['evidence'])
        self.assertFalse(result['retrieval_policy']['lexical_support_filter_applied'])

    def temporal_target(self):
        path = self.home/'source/2020-01-01.md'
        path.write_text('# 合成旧记录\n\n今天完成了白桦树统计实验并检查了采样结果。\n')
        config = json.loads((self.home/'sources.yaml').read_text())
        config['sources'][0]['model_paths'].append(path.name)
        (self.home/'sources.yaml').write_text(json.dumps(config))
        with Index(self.home/'index.sqlite3', load_pa1_config(self.home)) as index:
            index.reconcile()
        hit = self.search('今天完成了白桦树统计实验', infer_time_window=False)['evidence'][0]
        return hit

    def test_quoted_relative_words_do_not_force_a_time_filter_in_explicit_mode(self):
        hit = self.temporal_target()
        self.assertFalse(self.search('今天完成了白桦树统计实验')['evidence'])
        explicit = self.search('今天完成了白桦树统计实验', infer_time_window=False)
        self.assertEqual(explicit['evidence'][0]['chunk_id'], hit['chunk_id'])
        self.assertIsNone(explicit['time_window'])
        window = {'start':'2026-10-01','end':'2026-10-01','basis':'test','unknown_dates':'excluded'}
        self.assertFalse(self.search('今天完成了白桦树统计实验', infer_time_window=False,time_window=window)['evidence'])

    def test_private_eval_explicit_and_legacy_policies_are_reported_separately(self):
        e = self.temporal_target()
        dataset = {'protocol':'retrieval-private-qrels-v1','design':'known_span_smoke',
            'source_bindings':{'notes':root_identity(self.home/'source')},'cases':[{
                'query':'今天完成了白桦树统计实验','source_ids':['notes'],
                'targets':[{k:e[k] for k in ('document_id','content_hash','char_start','char_end')}]}]}
        explicit = evaluate_private(self.home,dataset)
        old = evaluate_private(self.home,dataset,temporal_policy='legacy_auto')
        self.assertEqual(explicit['dataset_sha256'],old['dataset_sha256'])
        self.assertEqual(explicit['evidence_recall_at_k'],1.)
        self.assertEqual(old['evidence_recall_at_k'],0.)
        self.assertEqual(explicit['protocol'],'retrieval-private-eval-v2')

    def test_quality_bundle_binds_policy_and_includes_it_in_final_byte_budget(self):
        bundle = build_bundle_v2(self.home,'缓存一致性',mode='lexical',reranker=Scorer(),min_score=0.,
                                quality_profile='strict-lexical-v1',infer_time_window=False)
        payload = bundle.cloud_input(self.home)
        self.assertEqual(payload['protocol'],'retrieval-v2.3')
        self.assertIn('retrieval_policy',payload)
        self.assertLessEqual(len(json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()),bundle.max_bytes)
        before = bundle.fingerprint()
        bundle.retrieval_policy['infer_time_window'] = True
        self.assertNotEqual(before,bundle.fingerprint())

    def test_invalid_policy_is_rejected_without_running_a_model(self):
        for options in ({'infer_time_window':1},{'quality_profile':'unknown'},
                        {'quality_profile':'strict-lexical-v1'}):
            with self.assertRaises(ValueError):
                self.search('缓存一致性',**options)


if __name__=='__main__':
    unittest.main()

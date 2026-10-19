import copy
import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from personal_asis.config import load_pa1_config, root_identity
from personal_asis.index import Index
from personal_asis.retrieval_eval import cases, evaluate, fixture, holdout_cases, retrieval_gate
from personal_asis.retrieval_private_eval import evaluate_private
from personal_asis.retrieval_v2 import (PROTOCOL, RERANK_PROTOCOL, RetrievalV2, build_bundle_v2,
                                        digest, encoded)
from personal_asis.reranking import LocalCrossEncoder


class Scorer:
    cache_key = 'a' * 64

    def __init__(self, function=None):
        self.seen = []
        self.function = function or (lambda text: 4. if '副本' in text else -5.)

    def score(self, query, passages):
        self.seen.extend(passages)
        return [self.function(p) for p in passages]


class RetrievalQualityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        fixture(self.home)

    def search(self, query='缓存一致性', **kwargs):
        with Index(self.home / 'index.sqlite3', load_pa1_config(self.home)) as index, RetrievalV2(index) as v2:
            return v2.search(query, provider='mimo', mode='lexical', **kwargs)

    def test_no_reranker_preserves_legacy_payload_and_bundle_fingerprint(self):
        result = self.search()
        self.assertEqual(result['protocol'], PROTOCOL)
        self.assertNotIn('reranking', result)
        bundle = build_bundle_v2(self.home, '缓存一致性', mode='lexical')
        expected = digest(encoded([PROTOCOL, bundle.query, bundle.provider, bundle.evidence, bundle.max_bytes]))
        self.assertEqual(bundle.fingerprint(), expected)
        self.assertEqual(set(bundle.cloud_input(self.home)), {'protocol', 'question', 'evidence'})

    def test_rejects_irrelevant_candidates_and_never_fills_empty_slots(self):
        scorer = Scorer()
        result = self.search(reranker=scorer, min_score=0.)
        self.assertEqual(result['protocol'], RERANK_PROTOCOL)
        self.assertEqual(len(result['evidence']), 1)
        self.assertIn('副本', result['evidence'][0]['excerpt'])
        empty = self.search('多个处理器如何维护缓存副本一致性', reranker=Scorer(lambda _: -4.), min_score=0.)
        self.assertFalse(empty['evidence'])
        self.assertEqual(empty['reranking']['state'], 'no_relevant_evidence')

    def test_permissions_metadata_time_and_channel_are_filtered_before_scoring(self):
        scorer = Scorer(lambda _: 2.)
        self.search('紫色猎鹰保密实验', reranker=scorer, min_score=0.)
        self.assertNotIn('紫色猎鹰', '\n'.join(scorer.seen))
        self.assertNotIn('量子香蕉', '\n'.join(scorer.seen))
        scorer.seen.clear()
        self.search('研究偏好', reranker=scorer, min_score=0., time_window={
            'start': '2026-10-01', 'end': '2026-10-01', 'basis': 'fixture', 'unknown_dates': 'excluded'})
        self.assertTrue(scorer.seen)
        self.assertNotIn('先考虑软件', '\n'.join(scorer.seen))
        scorer.seen.clear()
        result = self.search(reranker=scorer, min_score=0., channel='pwa')
        self.assertFalse(result['evidence'])
        self.assertFalse(scorer.seen)

    def test_bounded_pool_and_unscored_candidates_never_bypass_threshold(self):
        scorer = Scorer(lambda _: -1.)
        result = self.search('多个处理器如何维护缓存副本一致性', reranker=scorer, min_score=0., max_rerank_candidates=1)
        self.assertEqual(len(scorer.seen), 1)
        self.assertGreater(result['reranking']['unscored'], 0)
        self.assertFalse(result['evidence'])

    def test_exact_original_anchor_survives_a_low_model_score(self):
        result = self.search('我的批注', reranker=Scorer(lambda _: -100.), min_score=0.)
        self.assertTrue(result['evidence'])
        self.assertTrue(all('我的批注' in e['excerpt'] for e in result['evidence']))
        self.assertEqual(result['evidence'][0]['ranking']['reranking_basis'], 'exact_original')
        self.assertFalse(result['reranking']['answer_sufficiency_verified'])

    def test_invalid_policy_is_rejected_before_any_encoding_or_scoring(self):
        scorer = Scorer()
        for kwargs in ({'min_score': None}, {'min_score': float('nan')},
                       {'min_score': 0., 'max_rerank_candidates': 0}):
            with self.assertRaisesRegex(ValueError, 'invalid_reranking_policy'):
                self.search(reranker=scorer, **kwargs)
        self.assertFalse(scorer.seen)
        with self.assertRaisesRegex(ValueError, 'requires_local_model'):
            self.search(min_score=0.)

    def test_scorer_error_or_nonfinite_scores_fail_closed(self):
        for output in (None, [], [float('nan')] * 3, [float('inf')] * 3):
            with patch.object(Scorer, 'score', return_value=output):
                with self.assertRaisesRegex(ValueError, 'invalid_reranker_output'):
                    self.search(reranker=Scorer(), min_score=0.)
        with patch.object(Scorer, 'score', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                self.search(reranker=Scorer(), min_score=0.)

    def test_bundle_accounts_for_quality_bytes_and_fingerprints_policy(self):
        kwargs = dict(mode='lexical', reranker=Scorer(), min_score=0.)
        bundle = build_bundle_v2(self.home, '缓存一致性', **kwargs)
        payload = bundle.cloud_input(self.home)
        self.assertEqual(payload['protocol'], RERANK_PROTOCOL)
        self.assertLessEqual(len(encoded(payload).encode()), bundle.max_bytes)
        self.assertFalse(payload['reranking']['answer_sufficiency_verified'])
        other = build_bundle_v2(self.home, '缓存一致性', **{**kwargs, 'min_score': 1.})
        self.assertNotEqual(bundle.fingerprint(), other.fingerprint())
        bundle.evidence[0]['excerpt'] = 'tampered'
        with self.assertRaises(ValueError):
            bundle.cloud_input(self.home)

    def test_local_loader_refuses_remote_ids_symlinks_and_custom_code(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            LocalCrossEncoder('not/a/local/model')
        path = self.home / 'model'
        path.mkdir()
        for name in ('config.json', 'tokenizer_config.json'):
            (path / name).write_text(json.dumps({'auto_map': {'x': 'custom'}}))
        (path / 'tokenizer.json').write_text('{}')
        (path / 'model.safetensors').write_bytes(b'synthetic')
        with self.assertRaisesRegex(ValueError, 'unsupported'):
            LocalCrossEncoder(path)
        link = self.home / 'model-link'
        link.symlink_to(path)
        with self.assertRaises(ValueError):
            LocalCrossEncoder(link)

    def dataset(self):
        result = self.search()
        e = result['evidence'][0]
        return {'protocol': 'retrieval-private-qrels-v1',
                'source_bindings': {'notes': root_identity(self.home / 'source')},
                'cases': [{'query': '缓存一致性', 'source_ids': ['notes'], 'targets': [{k: e[k]
                    for k in ('document_id', 'content_hash', 'char_start', 'char_end')}]},
                          {'query': '完全不存在的火星独角兽', 'source_ids': ['notes'], 'targets': []}]}

    def test_private_qrels_report_omits_query_identity_and_source_text(self):
        dataset = self.dataset()
        original = copy.deepcopy(dataset)
        report = evaluate_private(self.home, dataset)
        self.assertEqual(report['evidence_recall_at_k'], 1.)
        self.assertTrue(report['root_and_target_versions_checked'])
        output = encoded(report)
        for value in ('缓存一致性', str(self.home), dataset['cases'][0]['targets'][0]['document_id']):
            self.assertNotIn(value, output)
        self.assertFalse(report['production_replacement_gate_passed'])
        self.assertEqual(dataset, original)

    def test_private_qrels_reject_stale_versions_root_changes_and_revocation(self):
        for field, value in [('content_hash', 'changed'), ('char_end', 99999)]:
            dataset = self.dataset()
            dataset['cases'][0]['targets'][0][field] = value
            with self.assertRaisesRegex(ValueError, 'stale_or_denied'):
                evaluate_private(self.home, dataset)
        dataset = self.dataset()
        dataset['source_bindings']['notes'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'root_changed'):
            evaluate_private(self.home, dataset)
        dataset = self.dataset()
        path = self.home / 'sources.yaml'
        config = json.loads(path.read_text())
        config['sources'][0]['model_providers'] = []
        path.write_text(json.dumps(config))
        with self.assertRaisesRegex(ValueError, 'stale_or_denied'):
            evaluate_private(self.home, dataset)

    def test_frozen_dataset_is_unchanged_and_holdout_is_separate(self):
        self.assertEqual(len(cases()), 39)
        self.assertFalse({c['query'] for c in cases()} & {c['query'] for c in holdout_cases()})
        reference = evaluate(self.home, 'v2')
        self.assertEqual(reference['dataset_sha256'], 'd199f5981b44bbf4b0e75aae1ec023a2bc3f3e3ee208bdd2667404461a153a5d')
        candidate = copy.deepcopy(reference)
        candidate['negative_cases_passed'] = candidate['negative_cases_total']
        candidate['evidence_recall_at_k'] -= .1
        gate = retrieval_gate(reference, candidate)
        self.assertFalse(gate['retrieval_gate_passed'])
        self.assertFalse(gate['production_replacement_gate_passed'])
        self.assertFalse(gate['checks']['recall_no_regression'])

    def test_cli_quality_diagnostics_omit_sensitive_text(self):
        from personal_asis.cli import main
        with patch('personal_asis.reranking.LocalCrossEncoder', return_value=Scorer()), \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main(['--home', str(self.home), 'retrieval-v2', 'search', '--query', '缓存一致性',
                         '--reranker-dir', str(self.home / 'synthetic-model'), '--rerank-min-score', '0',
                         '--diagnostics-only'])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload['protocol'], RERANK_PROTOCOL)
        self.assertEqual(payload['reranking']['scored'], 3)
        self.assertNotIn('缓存一致性', output.getvalue())
        self.assertNotIn(str(self.home), output.getvalue())

    def test_private_cli_refuses_public_dataset_and_hides_error_details(self):
        from personal_asis.retrieval_private_eval import main
        dataset = self.home / 'qrels.json'
        dataset.write_text(json.dumps(self.dataset()))
        dataset.chmod(0o644)
        destination = self.home / 'report.json'
        argv = ['private-eval', '--home', str(self.home), '--dataset', str(dataset), '--output', str(destination)]
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO) as output:
            code = main()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue()), {'error': 'private_retrieval_evaluation_failed'})
        self.assertFalse(destination.exists())
        dataset.chmod(0o600)
        with patch('sys.argv', argv), patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(), 0)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('缓存一致性', destination.read_text())


if __name__ == '__main__':
    unittest.main()

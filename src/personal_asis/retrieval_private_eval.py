"""Version-bound local qrels evaluation. Reports never contain queries or source identities."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import statistics
import time
from unittest.mock import patch

from .config import load_pa1_config, root_identity
from .index import Index
from .retrieval_v2 import RetrievalV2


def evaluate_private(home, dataset, *, mode='lexical', encoder=None, reranker=None,
                     min_score=None, max_rerank_candidates=40, k=5, quality_profile=None,
                     temporal_policy='explicit'):
    home = Path(home)
    if (dataset.get('protocol') != 'retrieval-private-qrels-v1'
            or not isinstance(dataset.get('cases'), list) or not 1 <= len(dataset['cases']) <= 100
            or not isinstance(dataset.get('source_bindings'), dict) or not dataset['source_bindings']
            or type(k) is not int or not 1 <= k <= 100):
        raise ValueError('invalid_private_qrels')
    design = dataset.get('design', 'unspecified')
    if design not in ('human_qrels', 'known_span_smoke', 'assistant_authored_natural', 'unspecified'):
        raise ValueError('invalid_private_qrels_design')
    if temporal_policy not in ('explicit', 'legacy_auto'):
        raise ValueError('invalid_private_temporal_policy')
    rows = []
    for ordinal, case in enumerate(dataset['cases'], 1):
        sources, targets = case.get('source_ids'), case.get('targets')
        if (not isinstance(sources, list) or not sources or set(sources) - set(dataset['source_bindings'])
                or not isinstance(targets, list) or len(targets) > 6):
            raise ValueError('invalid_private_qrels_case')
        with Index(home / 'index.sqlite3', load_pa1_config(home)) as index, RetrievalV2(index) as v2:
            current = {s.id: s for s in index.config.sources}
            if any(s not in current or root_identity(current[s].root) != dataset['source_bindings'][s]
                   for s in sources):
                raise ValueError('private_qrels_root_changed')
            v2.sync()
            allowed = v2._allowed('mimo', sources, 'local', case.get('time_window'))
            for target in targets:
                value = v2.documents.get(target.get('document_id'))
                if (value is None or target['document_id'] not in allowed
                        or value[0]['content_hash'] != target.get('content_hash')
                        or type(target.get('char_start')) is not int or type(target.get('char_end')) is not int
                        or not 0 <= target['char_start'] < target['char_end'] <= len(value[1])):
                    raise ValueError('private_qrels_target_stale_or_denied')
            started = time.perf_counter()
            result = v2.search(case.get('query'), source_ids=sources, provider='mimo', mode=mode,
                               encoder=encoder, reranker=reranker, min_score=min_score,
                               max_rerank_candidates=max_rerank_candidates, limit=k,
                               time_window=case.get('time_window'), quality_profile=quality_profile,
                               infer_time_window=temporal_policy == 'legacy_auto')
            evidence = result['evidence']
            def matches(e, t):
                return (e['document_id'] == t['document_id'] and e['content_hash'] == t['content_hash']
                        and e['char_start'] <= t['char_start'] < t['char_end'] <= e['char_end'])
            matched = sum(any(matches(e, t) for e in evidence) for t in targets)
            relevant = sum(any(matches(e, t) for t in targets) for e in evidence)
            rows.append({'case_number': ordinal, 'expected': len(targets), 'matched': matched,
                         'returned': len(evidence), 'relevant': relevant,
                         'latency_ms': round((time.perf_counter() - started) * 1000, 2),
                         'mode': result['mode'], 'degraded': result['degradation'] is not None})
    positive = [r for r in rows if r['expected']]
    nonempty = [r for r in rows if r['returned']]
    latency = sorted(r['latency_ms'] for r in rows)
    return {'protocol': 'retrieval-private-eval-v2', 'synthetic_only': False,
            'temporal_policy': temporal_policy, 'quality_profile': quality_profile,
            'dataset_design': design, 'manual_relevance_judgment': design == 'human_qrels',
            'dataset_sha256': hashlib.sha256(json.dumps(dataset, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'questions': len(rows), 'k': k, 'model_generation_calls': 0,
            'evidence_recall_at_k': statistics.mean(r['matched'] / r['expected'] for r in positive) if positive else None,
            'precision_at_k': statistics.mean(r['relevant'] / k for r in rows),
            'returned_precision_macro_nonempty': statistics.mean(r['relevant'] / r['returned'] for r in nonempty) if nonempty else None,
            'negative_cases_total': sum(not r['expected'] for r in rows),
            'negative_cases_passed': sum(not r['expected'] and not r['returned'] for r in rows),
            'latency_ms': {'p50': statistics.median(latency), 'p95': latency[min(len(latency) - 1, int(len(latency) * .95))]},
            'root_and_target_versions_checked': True, 'degraded_questions': sum(r['degraded'] for r in rows),
            'query_text_titles_paths_document_ids_or_excerpts_in_report': False,
            'answer_faithfulness_verified': False, 'answer_relevancy_verified': False,
            'production_replacement_gate_passed': False, 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--dataset', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('lexical', 'semantic', 'hybrid'), default='lexical')
    parser.add_argument('--reranker-dir', type=Path)
    parser.add_argument('--min-score', type=float)
    parser.add_argument('--quality-profile', choices=['strict-lexical-v1'])
    parser.add_argument('--temporal-policy', choices=['explicit', 'legacy_auto'], default='explicit')
    args = parser.parse_args()
    try:
        repo = Path(__file__).resolve().parents[2]
        if (args.dataset.is_symlink() or args.output.is_symlink()
                or any(p.resolve().is_relative_to(repo) for p in (args.dataset, args.output))
                or args.dataset.stat().st_size > 262144
                or args.dataset.stat().st_mode & 0o077):
            raise ValueError('private_eval_requires_private_files_outside_checkout')
        if bool(args.reranker_dir) != (args.min_score is not None):
            raise ValueError('reranking_requires_local_model_and_explicit_threshold')
        dataset = json.loads(args.dataset.read_text())
        # Includes model loading: runtime cannot download, phone home or call a provider.
        with patch.object(socket.socket, 'connect', side_effect=OSError('private_eval_offline_only')):
            encoder, reranker = None, None
            if args.mode != 'lexical':
                from .pa1 import settings, encoder_for
                encoder, reason = encoder_for(settings(args.home))
                if encoder is None:
                    raise ValueError(reason)
            if args.reranker_dir:
                from .reranking import LocalCrossEncoder
                reranker = LocalCrossEncoder(args.reranker_dir)
            report = evaluate_private(args.home, dataset, mode=args.mode, encoder=encoder,
                                      reranker=reranker, min_score=args.min_score,
                                      quality_profile=args.quality_profile, temporal_policy=args.temporal_policy)
        from .reading import private_file
        private_file(args.output, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
        print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError, RuntimeError, sqlite3.Error):
        # No exception text: paths and query fragments must never escape on failure.
        print(json.dumps({'error': 'private_retrieval_evaluation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

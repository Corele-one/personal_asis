"""Offline retrieval benchmark. Only fixed synthetic text is ever persisted here."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
import time
import uuid

from .config import load_pa1_config
from .index import Index
from .retrieval import retrieve


FACTS = [
    ('coherence', '缓存一致性', '缓存一致性协议通过失效消息维护多个处理器的副本。', '多个处理器如何维护缓存副本一致性'),
    ('numa', 'NUMA', 'NUMA 的远程内存访问延迟高于本地内存。', 'NUMA远程内存的延迟是多少'),
    ('tlb', 'TLB', 'TLB 缓存虚拟地址到物理地址的页表映射。', '虚拟地址的页表映射为何使用TLB缓存'),
    ('pipeline', '流水线', '流水线遇到分支预测错误需要冲刷流水级。', '分支预测错误时流水线如何处理'),
    ('bandwidth', '内存带宽', '矩阵乘法的内存带宽需求可通过分块复用降低。', '矩阵乘法如何降低内存带宽需求'),
    ('power', '动态功耗', '动态功耗随开关频率和电压平方变化。', '开关频率与电压怎样影响动态功耗'),
    ('journal', '睡前记录', '睡前记录是本人自报的准备入睡时间，不能当作实际睡眠时长。', '睡前记录是否能代表实际睡眠时长'),
    ('career', '申请准备', '申请准备需要核对官方截止日期并整理个人项目经历。', '整理个人项目经历怎样帮助申请准备'),
    ('english', 'cache invalidation', 'cache invalidation removes obsolete entries after updates.', 'How does cache invalidation remove obsolete entries?'),
    ('roofline', 'Roofline', 'Roofline compares arithmetic intensity against memory bandwidth.', 'How does Roofline use arithmetic intensity?'),
    ('person', 'Ada Lovelace', 'Ada Lovelace wrote notes on the analytical engine.', 'What notes did Ada Lovelace write?'),
    ('title', '精确标题青铜计划', '青铜计划的验收条件是提交可复现的实验报告。', '青铜计划怎样验收实验报告'),
]


def cases():
    result = []
    for key, term, body, paraphrase in FACTS:
        for suffix, query in [('exact', term), ('natural', paraphrase)]:
            result.append({'id': key + '-' + suffix, 'mode': 'fact' if suffix == 'natural' else 'exact',
                           'query': query, 'targets': [body]})
    result += [
        {'id': 'tail', 'mode': 'long_document', 'query': '长文尾部尾声结论', 'targets': ['尾声结论：远程访问应批量合并以减少往返。']},
        {'id': 'neighbors', 'mode': 'long_document', 'query': '窗口边界的相邻段落', 'targets': ['窗口边界的相邻段落必须保留来源位置。']},
        {'id': 'multi-chunk', 'mode': 'synthesis', 'query': '协议甲与协议乙对比', 'targets': ['协议甲通过广播失效实现一致性。', '协议乙通过目录跟踪共享者。']},
        {'id': 'multi-doc', 'mode': 'synthesis', 'query': '缓存一致性与动态功耗', 'targets': [FACTS[0][2], FACTS[5][2]]},
        {'id': 'timeline', 'mode': 'timeline', 'query': '研究偏好', 'targets': ['研究偏好：先考虑软件。', '研究偏好：转向软硬协同。'],
         'time_window': {'start': '2026-09-01', 'end': '2026-10-01', 'basis': 'fixture', 'unknown_dates': 'excluded'}},
        {'id': 'date-filter', 'mode': 'timeline', 'query': '研究偏好', 'targets': ['研究偏好：转向软硬协同。'],
         'time_window': {'start': '2026-10-01', 'end': '2026-10-01', 'basis': 'fixture', 'unknown_dates': 'excluded'}},
        {'id': 'duplicate-arrival', 'mode': 'external', 'query': '互连延迟', 'targets': ['互连延迟取决于拓扑和链路拥塞。']},
        {'id': 'author', 'mode': 'external', 'query': '拓扑和链路拥塞', 'targets': ['互连延迟取决于拓扑和链路拥塞。']},
        {'id': 'annotation', 'mode': 'external', 'query': '我的批注', 'targets': ['我的批注：需要自己复现实验。']},
        {'id': 'metadata', 'mode': 'insufficient', 'query': '量子香蕉缺少正文', 'targets': []},
        {'id': 'missing', 'mode': 'insufficient', 'query': '火星独角兽虹膜', 'targets': []},
        {'id': 'permission', 'mode': 'denied', 'query': '紫色猎鹰保密实验', 'targets': []},
        {'id': 'cross-language', 'mode': 'semantic_paraphrase', 'query': 'How are copies on multiple processors kept consistent?', 'targets': [FACTS[0][2]]},
        {'id': 'zh-paraphrase', 'mode': 'semantic_paraphrase', 'query': '多核机器里的拷贝怎么避免读到旧值', 'targets': [FACTS[0][2]]},
        {'id': 'en-paraphrase', 'mode': 'semantic_paraphrase', 'query': 'discarding outdated stored results after modifications', 'targets': [FACTS[8][2]]},
    ]
    return result


def fixture(home):
    """Use the real local-source/cache contracts, never a user's source directory."""
    from .reading import configure, ReadingCache, classify
    from .reading_sources import Article
    root = home / 'source'
    root.mkdir()
    for key, term, body, _ in FACTS:
        (root / (key + '.md')).write_text('# ' + term + '\n\n' + body + '\n')
    (root / 'long.md').write_text('# 长文\n\n' + '\n\n'.join('背景说明与实验步骤。' * 30 for _ in range(24))
        + '\n\n## 尾部\n\n尾声结论：远程访问应批量合并以减少往返。\n\n窗口边界的相邻段落必须保留来源位置。\n')
    (root / 'protocols.md').write_text('# 协议比较\n\n协议甲通过广播失效实现一致性。\n\n协议乙通过目录跟踪共享者。\n')
    for name, body in [('2026-09-01', '先考虑软件'), ('2026-10-01', '转向软硬协同')]:
        (root / (name + '.md')).write_text('# 研究记录\n\n研究偏好：' + body + '。\n')
    (root / 'denied.md').write_text('# 无许可\n\n紫色猎鹰保密实验禁止披露。\n')
    paths = [p.name for p in root.glob('*.md') if p.name != 'denied.md']
    (home / 'sources.yaml').write_text(json.dumps({'node_id': 'synthetic', 'sources': [{
        'id': 'notes', 'root': str(root), 'policy': 'normal', 'index': True,
        'remote_metadata': False, 'model_providers': ['mimo'], 'model_paths': paths}]}))
    for connector in ['folo', 'wucai']:
        configure(home, connector)
        item = Article('same-work', '互连论文', 'https://example.org/interconnect', author='Synthetic Author',
                       author_text='互连延迟取决于拓扑和链路拥塞。', content_kind='feed_content',
                       user_note='我的批注：需要自己复现实验。' if connector == 'wucai' else '')
        with ReadingCache(home, connector) as cache:
            cache.put(item, 'selections')
        classify(home, connector, item.item_id, 'normal')
    with ReadingCache(home, 'folo') as cache:
        cache.put(Article('meta', '量子香蕉缺少正文', 'https://example.org/meta'), 'subscriptions')
    classify(home, 'folo', 'meta', 'normal')
    data = json.loads((home / 'sources.yaml').read_text())
    for source in data['sources'][1:]:
        source.update(model_providers=['mimo'], model_all_files=True)
    (home / 'sources.yaml').write_text(json.dumps(data))
    with Index(home / 'index.sqlite3', load_pa1_config(home)) as index:
        index.reconcile()
        # Stabilize tie-breaking across independent fixture runs. Production UUIDs stay untouched.
        with index.db:
            for row in index.db.execute('SELECT document_id,source_id,path FROM documents').fetchall():
                stable = str(uuid.uuid5(uuid.NAMESPACE_URL, row['source_id'] + '/' + row['path']))
                for table in ('documents', 'versions', 'extractions'):
                    index.db.execute(f'UPDATE {table} SET document_id=? WHERE document_id=?', (stable, row['document_id']))


def evaluate(home, version, mode='lexical', encoder=None, k=5):
    rows = []
    with Index(home / 'index.sqlite3', load_pa1_config(home)) as index:
        for case in cases():
            start = time.perf_counter()
            if version == 'baseline':
                found = retrieve(index, case['query'], k, 'mimo', encoder,
                                 time_window=case.get('time_window'))
            else:
                from .retrieval_v2 import RetrievalV2
                with RetrievalV2(index) as v2:
                    found = v2.search(case['query'], limit=k, provider='mimo', mode=mode,
                                      encoder=encoder, time_window=case.get('time_window'))
            evidence = found['evidence']
            targets = case['targets']
            # Match evidence spans, not just document IDs. Duplicate arrivals do not add recall.
            matched = {t for t in targets if any(t in e['excerpt'] for e in evidence)}
            relevant = sum(any(t in e['excerpt'] for t in targets) for e in evidence)
            recall = len(matched) / len(targets) if targets else None
            precision = relevant / k
            returned_precision = relevant / len(evidence) if evidence else None
            forbidden = any('紫色猎鹰保密实验禁止披露' in e['excerpt'] for e in evidence)
            missing_in_returned_docs = any(t in index._current(index.db.execute(
                'SELECT * FROM documents WHERE document_id=?', (e['document_id'],)).fetchone())[2]
                for t in set(targets) - matched for e in evidence)
            failure = ('unexpected_evidence' if not targets and evidence else
                       'retrieval_miss' if targets and not evidence else
                       'context_span_gap' if missing_in_returned_docs else
                       'retrieval_ranking_gap' if targets and len(matched) < len(targets) else None)
            rows.append({'id': case['id'], 'query_mode': case['mode'], 'retrieval_mode': found.get('mode'),
                         'evidence_recall_at_k': recall, 'precision_at_k': precision,
                         'returned_precision': returned_precision, 'forbidden_evidence_leak': forbidden,
                         'returned': len(evidence), 'expected': len(targets), 'matched': len(matched),
                         'failure': failure, 'latency_ms': round((time.perf_counter() - start) * 1000, 2)})
    positives = [r for r in rows if r['expected']]
    precisions = [r['precision_at_k'] for r in rows if r['precision_at_k'] is not None]
    code_files = ['retrieval.py', 'semantic.py', 'index.py', 'retrieval_time.py', 'config.py']
    if version == 'v2':
        code_files += ['retrieval_v2.py']
    return {'protocol': 'retrieval-eval-v1', 'version': version, 'requested_mode': mode, 'k': k,
            'dataset_sha256': hashlib.sha256(json.dumps([FACTS, cases(), 'fixture-long24x30-v1'], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            'implementation_files_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in code_files},
            'stage_coverage': {'candidate_and_evidence_retrieval': True, 'context_span_loss': True,
                               'answer_faithfulness': False, 'answer_relevancy': False},
            'synthetic_only': True, 'model_generation_calls': 0,
            'semantic_backend': 'supplied' if encoder else 'none', 'questions': len(rows),
            'evidence_recall_at_k': sum(r['evidence_recall_at_k'] for r in positives) / len(positives),
            'precision_at_k': sum(precisions) / len(precisions) if precisions else None,
            'negative_cases_passed': sum(not r['returned'] for r in rows if not r['expected']),
            'forbidden_evidence_leaks': sum(r['forbidden_evidence_leak'] for r in rows),
            'metric_semantics': {'recall': 'macro over positive questions, exact expected span in retrieved evidence',
                                 'precision': 'relevant returned spans / K; macro over all questions, unfilled slots count zero',
                                 'returned_precision': 'relevant spans / returned spans; null for empty results',
                                 'negative': 'empty result required; unrelated authorized matches fail abstention, not permission'},
            'failure_counts': dict(Counter(r['failure'] for r in rows if r['failure'])), 'cases': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', choices=['baseline', 'v2'], default='baseline')
    parser.add_argument('--mode', choices=['lexical', 'semantic', 'hybrid'], default='lexical')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--semantic-home', type=Path, help='Only read existing local encoder settings; no source data or model API')
    args = parser.parse_args()
    encoder = None
    if args.semantic_home:
        from .pa1 import settings, encoder_for
        encoder, reason = encoder_for(settings(args.semantic_home))
        if encoder is None:
            raise ValueError(reason)
    with tempfile.TemporaryDirectory(prefix='asis-eval-') as temporary:
        home = Path(temporary).resolve()
        fixture(home)
        result = evaluate(home, args.version, args.mode, encoder)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(payload)
    else:
        print(payload, end='')


if __name__ == '__main__':
    main()

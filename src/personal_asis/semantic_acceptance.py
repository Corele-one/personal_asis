"""Repeatable real-weight acceptance using only built-in synthetic evidence."""

import json
from pathlib import Path
import tempfile
import time

from .config import load_config
from .index import Index
from .retrieval import build_bundle, retrieve


DOCUMENTS = {
    'cache.md':'# Cache maintenance\n\nExpired items are removed from the local store to avoid serving stale data.\n',
    'coherence.md':'# Processor architecture\n\nA coherence protocol ensures that all processors observe consistent copies of shared memory.\n',
    'scholarship.md':'# 奖学金材料\n\n申请助学资助需要成绩单、推荐信以及家庭经济情况证明。\n',
    'cooking.md':'# Kitchen guide\n\nTo prepare pumpkin soup, simmer diced squash with water and blend until smooth.\n',
    'tail.md':'# Synthetic long article\n\n'+('The sample describes ordinary garden flowers. '*320)+
              '\n\nUnderwater robots navigate using sonar echoes when satellite positioning is unavailable.\n',
    'private.md':'---\nsensitivity: private\n---\n# PRIVATE_CANARY\nsecret sonar CANARY\n',
    'unapproved.md':'# UNAPPROVED_CANARY\nsecret coherence CANARY\n',
}
CASES = [
    ('多个处理器如何保证共享数据副本相同', 'coherence.md'),
    ('How are outdated entries discarded?', 'cache.md'),
    ('What paperwork is needed for financial aid?', 'scholarship.md'),
    ('怎样制作南瓜浓汤', 'cooking.md'),
    ('水下机器人没有卫星信号怎样定位', 'tail.md'),
    ('How can submarines find their way without GPS?', 'tail.md'),
]


def run(encoder):
    with tempfile.TemporaryDirectory(prefix='asis-semantic-acceptance-') as directory:
        home=Path(directory)
        root=home/'source'
        root.mkdir()
        for name,text in DOCUMENTS.items():
            (root/name).write_text(text)
        config={'node_id':'synthetic','sources':[{'id':'synthetic','root':str(root),'policy':'normal',
                'model_providers':['mimo'],'model_paths':[name for name in DOCUMENTS
                    if name not in ('private.md','unapproved.md')]}]}
        (home/'sources.yaml').write_text(json.dumps(config))
        results=[]
        with Index(home/'index.sqlite3',load_config(home/'sources.yaml')) as index:
            index.reconcile()
            for query,expected in CASES:
                start=time.monotonic()
                result=retrieve(index,query,provider='mimo',encoder=encoder)
                top=result['evidence'][0] if result['evidence'] else None
                paths=[e['path_hint'] for e in result['evidence'][:3]]
                results.append({'query':query,'expected':expected,'actual':top['path_hint'] if top else None,
                                'top1':top is not None and top['path_hint']==expected,
                                'top3':expected in paths, 'retrieved':paths,
                                'seconds':round(time.monotonic()-start,3),
                                'mode':result['mode'],'vector_cache':result['vector_cache']})
                if result['mode']!='hybrid_semantic' or result['policy_denied']!=2:
                    raise ValueError('real_semantic_or_permission_acceptance_failed')
                if any('CANARY' in e['excerpt'] for e in result['evidence']):
                    raise ValueError('semantic_canary_disclosure')
            start=time.monotonic()
            warm=retrieve(index,CASES[0][0],provider='mimo',encoder=encoder)
            warm_seconds=round(time.monotonic()-start,3)
        # The excerpt must come from the matched passage beyond the old 12k cap.
        bundle=build_bundle(home,CASES[-1][0],encoder=encoder)
        bundle.revalidate(home)
        tail=next(e for e in bundle.evidence if e['path_hint']=='tail.md')
        tail_passed='sonar echoes' in tail['excerpt'] and tail['line_start']>3
        return {'synthetic_only':True,'cloud_calls':0,'model_fingerprint':encoder.cache_key,
                'cases':results,'top1_passed':sum(r['top1'] for r in results),
                'top3_passed':sum(r['top3'] for r in results),'total':len(results),
                'tail_excerpt_verified':tail_passed,'warm_seconds':warm_seconds,
                'warm_cache':warm['vector_cache'],
                'acceptance_criterion':'all_expected_evidence_in_top3_with_exact_tail_excerpt',
                'passed':all(r['top3'] for r in results) and tail_passed
                    and warm['vector_cache']['encoded']==0}

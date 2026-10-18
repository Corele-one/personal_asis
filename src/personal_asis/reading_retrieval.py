"""Explicit account item → existing read-only fetch → versioned Chunk evidence.

Owner-local entry point; never classifies content or grants model/channel access.
Account content is never passed to the public Web Search Provider.
"""
from pathlib import Path

from .config import load_pa1_config
from .index import Index
from . import reading
from .reading_sources import identity
from .retrieval_v2 import RetrievalV2, ContextBundleV2, cloud_evidence, PROTOCOL
from .work import encoded


def snapshot(home, connector, item_id, query, *, fetch_body=False, provider=None,
             channel='local', source_client=None):
    if connector not in ('wucai', 'folo', 'xiaohongshu'):
        raise ValueError('reading_retrieval_connector_excluded')
    if provider not in (None, 'mimo') or channel not in ('local', 'feishu', 'pwa') or type(fetch_body) is not bool:
        raise ValueError('reading_retrieval_invalid_scope')
    home = Path(home)
    identity(item_id)
    from .data_policy import exclusion_reason
    if not isinstance(query,str) or not query.strip() or len(query)>512 or exclusion_reason('',query):
        raise ValueError('reading_retrieval_invalid_query')
    report = reading.fetch(home, connector, item_id, source_client) if fetch_body else None
    source_id = 'reading_' + connector
    with Index(home / 'index.sqlite3', load_pa1_config(home)) as index, RetrievalV2(index) as retrieval:
        result = retrieval.search(query, mode='lexical', provider=provider, source_ids=[source_id], channel=channel, limit=100)
        selected = []
        for e in result['evidence']:
            if e['source_item_id'] != item_id:
                continue
            payload = {'protocol': PROTOCOL, 'question': query, 'evidence': cloud_evidence(selected + [e])}
            if len(encoded(payload).encode()) <= 6144:
                selected.append(e)
    coverage = {'method': 'explicit_item_lexical', 'independent_works': len({e['work_key'] for e in selected}),
                'complete_article_verified': False, 'account_history_verified': False}
    bundle = ContextBundleV2(query, provider, selected, result['mode'], 6144, coverage)
    payload = bundle.cloud_input(home, channel)
    return {**payload, 'status': 'ok' if selected else 'no_authorized_current_body_match',
            'fetch': report, 'coverage': coverage, 'model_calls': 0,
            'provider_permission_checked': provider, 'channel_permission_checked': channel,
            'platform_mutations': 0}

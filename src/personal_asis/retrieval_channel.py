"""Explicit owner-only V2 lexical experiment over the existing encrypted relay."""

from .retrieval_v2 import PROTOCOL, build_bundle_v2


def snapshot(home, job):
    # No encoder, model API, billing ledger or work session. Provider permission is
    # an additional conservative filter; it does not imply a model call.
    bundle = build_bundle_v2(home, job['query'], source_ids=job['source_ids'],
                             provider='mimo', mode='lexical', channel=job['channel'], max_bytes=6144)
    bundle.cloud_input(home, job['channel'])
    fields = ('source_id', 'title', 'path_hint', 'chunk_id', 'line_start', 'line_end',
              'column_start', 'section_path', 'excerpt', 'content_kind', 'attribution_actor',
              'content_completeness', 'published_at', 'record_date')
    return {'kind': 'retrieval_v2', 'protocol': PROTOCOL, 'retrieval_mode': bundle.retrieval_mode,
            'coverage': bundle.coverage, 'model_calls': 0,
            'evidence': [{'id': f'E{i+1}', **{key: e[key] for key in fields}}
                         for i, e in enumerate(bundle.evidence)]}


def summary(value):
    lines = ['Retrieval V2 · 只读实验 · lexical', '未调用模型；以下是候选原文，不代表已经回答问题。']
    if value.get('error'):
        return '\n'.join(lines + ['没有可在当前权限与预算内展示的证据，或资料已变化；请核对来源或调整关键词。'])
    lines.append(f"候选段落 {len(value['evidence'])}；独立作品 {value['coverage']['independent_works']}。")
    for e in value['evidence']:
        lines.append(f"[{e['id']}] {e['title']}｜{e['source_id']}｜{e['path_hint']}｜第{e['line_start']}–{e['line_end']}行"
                     f"｜{e['content_kind']}｜{e['content_completeness']}\n{e['excerpt']}")
    lines.append('此实验不启用 Live 抓取、模型分析或后台工作；普通 /asis search 与 Agent 协议保持原样。')
    return '\n'.join(lines)

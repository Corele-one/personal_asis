"""Host-owned evidence disclosure policy, independent of remote transports."""

from pathlib import Path


def validate_result(home,result,channel='pwa'):
    """Revalidate actual evidence before disclosure, independently of cached model output."""
    if result.get('tools_protocol') in ('agent-web-v1','agent-web-v2','agent-web-v3'):
        if channel not in ('pwa','feishu'):
            raise ValueError('context_channel_denied')
        from .agent_web import MixedBundle
        MixedBundle({'question':'','evidence':result['evidence'],'mode':result['retrieval_mode'],
                     'degradation':result.get('degradation')}).revalidate(home,channel)
        return {**result,'evidence':[{k:v for k,v in e.items() if k!='original_uri'} for e in result['evidence']]}
    from .retrieval import ContextBundle
    from .research import ResearchBundle
    evidence=result['evidence']
    local=[e for e in evidence if e.get('kind')!='external']
    external=[e for e in evidence if e.get('kind')=='external']
    if external:
        bundle=ResearchBundle('',result['provider'],local+external,result['retrieval_mode'],
            None,len(local),result.get('research_strategy'))
    else:
        bundle=ContextBundle('',result['provider'],local,result['retrieval_mode'])
    bundle.revalidate(home)
    if channel not in ('pwa','feishu'):
        raise ValueError('context_channel_denied')
    from .config import load_pa1_config
    sources={s.id:s for s in load_pa1_config(Path(home)).sources}
    for entry in local:
        source=sources[entry['source_id']]
        if not source.allows_remote_evidence(entry['sensitivity']=='private',entry['path_hint']):
            raise ValueError('context_channel_permission_denied')
    # The remote owner gets evidence, but never the source filesystem URI.
    return {**result,'evidence':[{k:v for k,v in e.items() if k!='original_uri'} for e in evidence]}

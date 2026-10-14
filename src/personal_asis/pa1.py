"""First local PA1 slice: retrieval -> authorized bundle -> budget -> MiMo."""

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .config import load_config, load_pa1_config, root_identity
from .index import Index
from .model_budget import ModelBudget
from .model_provider import ENDPOINT, MiMo, ProviderRejected, ProviderUnknown, validate_answer
from .retrieval import build_bundle, retrieve, LocalSemanticEncoder


DEFAULTS = {"provider":"mimo","endpoint":ENDPOINT,"model":None,"enabled":False,
            "synthetic_only":True,"daily_tokens":100000,"monthly_tokens":1000000,
            "timezone":"Asia/Shanghai","max_completion_tokens":512,
            "max_prompt_bytes":8192,"semantic_model_dir":None,
            "semantic_query_prefix":"", "semantic_document_prefix":""}

SYNTHETIC_DOCUMENTS = {
    'cache.md':'# Synthetic cache\n\ncache invalidation removes a stale entry in this synthetic example.\n',
    'coherence.md':'# Synthetic coherence\n\ncache coherence keeps synthetic replicas consistent.\n',
    'private.md':'---\nsensitivity: private\n---\n# PRIVATE_CANARY\n\ncache PRIVATE_BODY_CANARY\n',
    'unapproved.md':'# UNAPPROVED_CANARY\n\ncache UNAPPROVED_BODY_CANARY\n'}


def verify_synthetic_bundle(bundle):
    approved={hashlib.sha256(SYNTHETIC_DOCUMENTS[p].encode()).hexdigest()
              for p in ['cache.md','coherence.md']}
    if bundle.query!='cache' or any(e['source_id']!='synthetic' or e['content_hash'] not in approved
                                    for e in bundle.evidence):
        raise ValueError('synthetic_fixture_content_required')


def settings(home):
    data=json.loads((Path(home)/'pa1.json').read_text())
    if not isinstance(data,dict) or set(data)-set(DEFAULTS):
        raise ValueError('invalid_pa1_configuration')
    data={**DEFAULTS,**data}
    if data['provider']!='mimo' or data['endpoint']!=ENDPOINT:
        raise ValueError('unsupported_model_provider_endpoint')
    if any(type(data[k]) is not bool for k in ['enabled','synthetic_only']):
        raise ValueError('invalid_pa1_configuration')
    for key,low,high in [('daily_tokens',1,100000000),('monthly_tokens',1,1000000000),
                         ('max_completion_tokens',1,4096),('max_prompt_bytes',512,16384)]:
        if type(data[key]) is not int or not low<=data[key]<=high:
            raise ValueError('invalid_pa1_configuration')
    if data['monthly_tokens']<data['daily_tokens'] or data['timezone']!='Asia/Shanghai':
        raise ValueError('invalid_pa1_configuration')
    if data['model'] is not None and not isinstance(data['model'],str):
        raise ValueError('invalid_pa1_configuration')
    directory=data['semantic_model_dir']
    if directory is not None and (not isinstance(directory,str) or not Path(directory).expanduser().is_absolute()):
        raise ValueError('semantic_model_requires_local_absolute_directory')
    for key in ('semantic_query_prefix', 'semantic_document_prefix'):
        if not isinstance(data[key],str) or len(data[key])>80:
            raise ValueError('invalid_semantic_prefix')
    return data


def configure(home, model=None, enabled=None, semantic_model_dir=None,
              semantic_query_prefix=None, semantic_document_prefix=None, disable_semantic=False,
              synthetic_only=None):
    home=Path(home)
    home.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=home/'pa1.json'
    data=settings(home) if path.exists() else DEFAULTS.copy()
    if model is not None:
        MiMo('validation',model)
        data['model']=model
    if enabled is not None:
        data['enabled']=enabled
    if synthetic_only is not None:
        if type(synthetic_only) is not bool:
            raise ValueError('invalid_pa1_configuration')
        data['synthetic_only']=synthetic_only
    if disable_semantic:
        if semantic_model_dir is not None:
            raise ValueError('semantic_enable_disable_are_mutually_exclusive')
        data['semantic_model_dir']=None
    elif semantic_model_dir is not None:
        directory=Path(semantic_model_dir).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise ValueError('local_semantic_model_missing')
        data['semantic_model_dir']=str(directory)
    for key,value in [('semantic_query_prefix',semantic_query_prefix),
                      ('semantic_document_prefix',semantic_document_prefix)]:
        if value is not None:
            if not isinstance(value,str) or len(value)>80:
                raise ValueError('invalid_semantic_prefix')
            data[key]=value
    temporary=path.with_suffix('.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as file:
        json.dump(data,file,ensure_ascii=False,indent=2)
        file.write('\n')
    temporary.replace(path)
    return data


def authorize_current_files(home, source_ids, include_private=False, all_source_files=False):
    """Grant model use in independent PA1 policy; never rewrite PA0 sources."""
    home=Path(home)
    config=load_config(home/'sources.yaml')
    if not source_ids or set(source_ids)-{s.id for s in config.sources}:
        raise ValueError('authorization_requires_known_source_ids')
    data=settings(home)
    grants={sid:[] for sid in source_ids}
    with Index(home/'index.sqlite3',config) as index:
        for row in index.db.execute('SELECT * FROM documents WHERE active=1').fetchall():
            if row['source_id'] not in grants:
                continue
            current=index._current(row)
            if current is None:
                continue
            source,_,_,private=current
            if source.index and (include_private or not private):
                grants[source.id].append(row['path'])
    path=home/'pa1-policy.json'
    policy=json.loads(path.read_text()) if path.exists() else {'version':1,'sources':{}}
    load_pa1_config(home)
    for source in config.sources:
        if source.id in grants:
            policy['sources'][source.id]={
                'root_identity':root_identity(source.root),
                'model_providers':[data['provider']] if source.policy!='private' or include_private else [],
                'private_model_providers':[data['provider']] if include_private else [],
                'model_paths':sorted(set(grants[source.id])),
                'model_all_files':all_source_files}
    temporary=path.with_suffix('.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as file:
        json.dump(policy,file,ensure_ascii=False,indent=2)
        file.write('\n')
    temporary.replace(path)
    return {'provider':data['provider'],'include_private':include_private,
            'granted_current_files':{sid:len(paths) for sid,paths in grants.items()},
            'new_paths_automatically_allowed':all_source_files,'policy_store':'pa1-policy.json',
            'pa0_source_configuration_changed':False}


def encoder_for(data):
    if data['semantic_model_dir'] is None:
        return None,'semantic_model_not_configured'
    try:
        return LocalSemanticEncoder(data['semantic_model_dir'],data['semantic_query_prefix'],
                                    data['semantic_document_prefix']),None
    except (ImportError,OSError,ValueError,RuntimeError,TypeError):
        return None,'semantic_backend_unavailable'


def revoke_sources(home, source_ids):
    home=Path(home)
    config=load_config(home/'sources.yaml')
    if not source_ids or set(source_ids)-{source.id for source in config.sources}:
        raise ValueError('authorization_requires_known_source_ids')
    path=home/'pa1-policy.json'
    if not path.exists():
        raise ValueError('separate_pa1_policy_not_configured')
    load_pa1_config(home)
    data=json.loads(path.read_text())
    for sid in source_ids:
        data['sources'].pop(sid,None)
    temporary=path.with_suffix('.tmp')
    descriptor=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as file:
        json.dump(data,file,ensure_ascii=False,indent=2)
        file.write('\n')
    temporary.replace(path)
    from .pa1_maintenance import clean
    return {'revoked_sources':source_ids,'policy_store':'pa1-policy.json','cleanup':clean(home)}


def budget(home, node_id, data):
    return ModelBudget(Path(home)/'pa1.sqlite3',node_id,data['daily_tokens'],data['monthly_tokens'],data['timezone'])


def analyze(home, query, request_id, provider=None, synthetic_home=None, source_ids=None):
    home=Path(home)
    data=settings(home)
    if not data['enabled']:
        raise ValueError('pa1_live_calls_disabled')
    if data['synthetic_only'] and synthetic_home is None:
        raise ValueError('pa1_synthetic_only_real_sources_disabled')
    source_home=Path(synthetic_home) if synthetic_home is not None else home
    config=load_pa1_config(source_home)
    encoder,degradation=encoder_for(data)
    bundle=build_bundle(source_home,query,data['provider'],encoder,source_ids)
    if data['synthetic_only']:
        verify_synthetic_bundle(bundle)
    client=provider or MiMo(config.node_id,data['model'])
    # Fail before reserving money/tokens if the credential is absent.
    secret=client.credential()
    payload=client.payload(bundle,data['max_completion_tokens'])
    prompt_bytes=len(json.dumps(payload['messages'],ensure_ascii=False).encode())
    if prompt_bytes>data['max_prompt_bytes']:
        raise ValueError('context_bundle_exceeds_prompt_limit')
    # Byte count bounds ordinary text tokenization; include a conservative
    # framing margin, then reconcile to authoritative provider usage.
    reservation=prompt_bytes+1024+data['max_completion_tokens']
    fingerprint=hashlib.sha256((bundle.fingerprint()+json.dumps(payload,sort_keys=True)+
                              json.dumps(data,sort_keys=True)).encode()).hexdigest()
    bundle.revalidate(source_home)
    ledger=budget(home,config.node_id,data)
    try:
        booked=ledger.reserve(request_id,fingerprint,reservation)
        if 'cached' in booked:
            bundle.revalidate(source_home)
            return {**booked['cached'],'cached':True,
                    'evidence':[{"id":f'E{i+1}',**e} for i,e in enumerate(bundle.evidence)],
                    'sensitivity':'private' if any(e['sensitivity']=='private' for e in bundle.evidence) else 'normal',
                    'retrieval_mode':bundle.retrieval_mode,'degradation':degradation or bundle.degradation}
        try:
            bundle.revalidate(source_home)
        except (OSError,ValueError):
            ledger.finish(request_id,'rejected',0)
            raise
        try:
            response=client.complete(payload,secret)
        except ProviderRejected:
            ledger.finish(request_id,'rejected',0)
            raise
        except (ProviderUnknown,OSError,ValueError):
            ledger.finish(request_id,'unknown')
            raise ValueError('model_call_unknown_reserved_budget_no_retry') from None
        total=response['usage']['total_tokens']
        try:
            if total>reservation or response['usage']['completion_tokens']>data['max_completion_tokens']:
                raise ValueError('provider_usage_exceeded_reservation')
            answer=validate_answer(response,bundle)
            bundle.revalidate(source_home)
        except (OSError,ValueError):
            ledger.finish(request_id,'invalid_output',total)
            raise
        result={**answer,'evidence':[{"id":f'E{i+1}',**e} for i,e in enumerate(bundle.evidence)],
                'sensitivity':'private' if any(e['sensitivity']=='private' for e in bundle.evidence) else 'normal',
                'usage':response['usage'],'retrieval_mode':bundle.retrieval_mode,
                'degradation':degradation or bundle.degradation,'request_id':request_id,'provider':'mimo',
                'model':data['model'],'cached':False}
        ledger.finish(request_id,'succeeded',total,result)
        return result
    finally:
        ledger.close()


def fixture(directory, node_id='mac'):
    base=Path(directory)
    source=base/'source'
    source.mkdir()
    for name,text in SYNTHETIC_DOCUMENTS.items():
        (source/name).write_text(text)
    data={'node_id':node_id,'sources':[{'id':'synthetic','root':str(source),'policy':'normal',
           'index':True,'remote_metadata':False,'model_providers':['mimo'],
           'model_paths':['cache.md','coherence.md']}]}
    (base/'sources.yaml').write_text(json.dumps(data))
    with Index(base/'index.sqlite3',load_config(base/'sources.yaml')) as index:
        index.reconcile()
    return base


def self_test(home, live=False, request_id=None):
    data=settings(home)
    node_id=load_config(Path(home)/'sources.yaml').node_id
    with tempfile.TemporaryDirectory(prefix='personal-asis-pa1-') as temporary:
        source_home=fixture(temporary,node_id)
        bundle=build_bundle(source_home,'cache')
        cloud=json.dumps(bundle.cloud_input(),ensure_ascii=False)
        if 'PRIVATE_CANARY' in cloud or 'UNAPPROVED_CANARY' in cloud or 'file:' in cloud or temporary in cloud:
            raise ValueError('synthetic_disclosure_filter_failed')
        if live:
            if not request_id:
                raise ValueError('live_self_test_requires_request_id')
            return analyze(home,'cache',request_id,synthetic_home=source_home)
        return {'synthetic_context_verified':True,'evidence_count':len(bundle.evidence),
                'retrieval_mode':bundle.retrieval_mode,'live_call_made':False,
                'daily_limit':data['daily_tokens'],'monthly_limit':data['monthly_tokens']}

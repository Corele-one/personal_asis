"""Bound-owner domain goal management; no model calls or source grants."""
from .coordinator import ProtocolError
from .data_policy import exclusion_reason
from .domain_context import DomainContexts
from .work import ROLES


def validate(command):
    if not isinstance(command,dict) or command.get('domain') not in ROLES:
        raise ProtocolError('domain_context_invalid_command')
    op=command.get('op')
    fields={'op','domain'}
    if op in ('set','forget'):fields.add('expected_revision')
    if op=='set':fields.update(('goal','constraints','source_ids','allow_model'))
    if op not in ('show','set','forget') or set(command)!=fields:
        raise ProtocolError('domain_context_invalid_command')
    if op!='show' and (type(command['expected_revision']) is not int or not 0<=command['expected_revision']<=1000000000):
        raise ProtocolError('domain_context_invalid_revision')
    if op=='set':
        if (not isinstance(command['goal'],str) or not command['goal'].strip() or len(command['goal'])>2000
                or not isinstance(command['constraints'],str) or len(command['constraints'])>4000
                or type(command['allow_model']) is not bool
                or not isinstance(command['source_ids'],list) or not 1<=len(command['source_ids'])<=20
                or any(not isinstance(s,str) or not 1<=len(s)<=64 for s in command['source_ids'])
                or exclusion_reason('',command['goal']+'\n'+command['constraints'])):
            raise ProtocolError('domain_context_invalid_or_credential_input')


def snapshot(home,domain):
    with DomainContexts(home) as store:
        try:value=store.show(domain)
        except ValueError as error:
            if str(error)!='domain_context_not_found':raise
            return {'kind':'domain_context','domain':domain,'revision':0,'goal':'','constraints':'',
                    'source_ids':[],'model_allowed':False,'needs_review':False,'deleted':False,'configured':False,
                    'model_called':False}
    return {'kind':'domain_context',**{k:v for k,v in value.items() if k!='roots'},
            'source_ids':sorted(value['roots']),'configured':not value['deleted'],'model_called':False}


def apply(home, command, request_id):
    validate(command)
    with DomainContexts(home) as store:
        if command['op']=='set':
            store.set(command['domain'],command['goal'],command['constraints'],command['source_ids'],request_id,
                      allow_model=command['allow_model'],expected_revision=command['expected_revision'])
        elif command['op']=='forget':
            store.forget(command['domain'],request_id,expected_revision=command['expected_revision'])
    return snapshot(home,command['domain'])

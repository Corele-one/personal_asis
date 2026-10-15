"""Opt-in specialist continuity; only that role sees its goals and prior analysis."""
from .domain_context import DomainContexts, validate_binding
from .work_history import retrieve_history, validate_history, provenance, prompt_history

VERSION='isolated-role-context-v1'


def prepare(home, roles, query, source_ids, run_id, channel=None, history=False):
    result={}
    with DomainContexts(home) as contexts:
        for role in roles:
            try:
                binding=contexts.for_model(role,source_ids)
            except ValueError as error:
                # Missing/unapproved goals do not become permission or invented goals.
                result[role]={'unavailable':str(error)}
                continue
            result[role]={'binding':binding,'history':retrieve_history(home,role,query,source_ids,
                exclude_run=run_id,channel=channel,role=role) if history else []}
    return result


def validate(home, contexts, roles, source_ids, channel=None):
    if not isinstance(contexts,dict) or set(contexts)!=set(roles):
        raise ValueError('agent_role_context_invalid')
    for role,value in contexts.items():
        if 'binding' not in value:
            if set(value)!={'unavailable'} or not isinstance(value['unavailable'],str):
                raise ValueError('agent_role_context_invalid')
            continue
        if set(value)!={'binding','history'} or value['binding']['domain']!=role:
            raise ValueError('agent_role_context_invalid')
        validate_binding(home,value['binding'],source_ids)
        validate_history(home,value['history'],value['binding'],source_ids,channel,role=role)


def messages(role, messages, context):
    if not context or 'binding' not in context:return messages
    from .work import encoded
    binding=context['binding']
    messages[1]['content']+='\n本人明确保存的本领域目标／约束：'+encoded({k:binding[k] for k in ('goal','constraints')})
    messages[1]['content']=prompt_history(messages[1]['content'],context['history']).replace(
        '必须调用 search_notes 核查原始资料','本机已完成本轮原始资料检索，仍须对照上面的证据核查')
    return messages


def summary(contexts):
    return [{'role':role,'used':'binding' in value,
             **({'revision':value['binding']['revision'],'history_used':provenance(value['history'])}
                if 'binding' in value else {'reason':value['unavailable']})}
            for role,value in contexts.items()]

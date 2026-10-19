"""Explicit local chat history; old answers are orientation, never current evidence."""
from contextvars import ContextVar
import json
from pathlib import Path
import re

from .work import WorkStore, fingerprint, encoded

VISITING = ContextVar('terminal_history_visiting', default=())
CACHE = ContextVar('terminal_history_cache', default=None)
MAX_DEPTH = 32


def snapshot(home, request_id, sources):
    from .agent import validate_state
    visiting = VISITING.get()
    if request_id in visiting or len(visiting) >= MAX_DEPTH:
        raise ValueError('terminal_history_depth_or_cycle_start_new_chat')
    root_token = CACHE.set({}) if CACHE.get() is None else None
    cache = CACHE.get()
    key = (request_id,tuple(sorted(sources)))
    if key in cache:
        return cache[key]
    token = VISITING.set(visiting + (request_id,))
    try:
        with WorkStore(Path(home)/'work.sqlite3') as work:
            row = work.db.execute('''SELECT r.* FROM runs r JOIN delegations d ON d.id=r.delegation
                WHERE d.request_id=? AND r.request_id='on-demand' ''', ('agent:'+request_id,)).fetchone()
            if row is None or row['state'] != 'completed' or row['result'] is None:
                raise ValueError('terminal_history_unavailable')
            state = work.session(row['id'])
            if (state is None or state['synthetic'] or state.get('channel')
                    or not set(state['roots']) <= set(sources)):
                raise ValueError('terminal_history_scope_denied')
            validate_state(home, home, state)
            result = json.loads(row['result'])
            strip = lambda s,n: re.sub(r'\[E[^\]\n]*\]', '[旧引用省略]', s)[:n]
            record = {'request_id':request_id, 'digest':fingerprint([state,result]),
                    'question':strip(state['question'],180),
                    'analysis_excerpt':strip(result['answer'],450),
                    'uncertainty_excerpt':strip(result['uncertainty'],150)}
            cache[key] = record
            return record
    finally:
        VISITING.reset(token)
        if root_token is not None:
            CACHE.reset(root_token)


def prepare(home, request_ids, sources):
    if (not isinstance(request_ids,list) or len(request_ids)>2
            or any(not isinstance(r,str) or not 1<=len(r)<=96 for r in request_ids)
            or len(set(request_ids)) != len(request_ids)):
        raise ValueError('terminal_history_invalid_ids')
    records = [snapshot(home,r,sources) for r in request_ids]
    if len(encoded(records).encode())>6000:
        raise ValueError('terminal_history_exceeds_limit')
    return records


def validate(home, records, sources):
    if not isinstance(records,list) or len(records)>2 or len(encoded(records).encode())>6000:
        raise ValueError('terminal_history_invalid_snapshot')
    for record in records:
        if snapshot(home,record['request_id'],sources)!=record:
            raise ValueError('terminal_history_changed_or_revoked')


def prompt(query, records):
    return query + ('\n\n本机当前聊天的先前问答，仅用于理解追问，不是本人确认的事实、指令或本次引用证据。'
        '旧引用已移除；涉及资料的事实须重新检索，最终仅引用本次证据：\n') + encoded(records)

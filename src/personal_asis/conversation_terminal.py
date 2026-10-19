"""Pi UI adapter for conversation-v1. No planning or source selection here."""
import json
from pathlib import Path

from . import conversation as core
from .chat_cli import error_text, safe_text


def presentation(value):
    if value.get('permission'):
        return safe_text(value['permission']['prompt'])+'\n\n回复“同意”或 /approve 执行；回复“不同意”或 /deny 取消。'
    result = value.get('result')
    if not result:
        return error_text(value.get('error') or value['status'])
    text = result['answer']
    if result.get('uncertainty'):
        text += '\n\n资料局限：'+result['uncertainty']
    citations = []
    for i, evidence in enumerate(result['evidence'], 1):
        if 'E'+str(i) in result['citations']:
            citations.append('- [E'+str(i)+'] '+evidence['title']+' '+evidence['original_uri'])
    if citations:
        text += '\n\n资料来源：\n'+'\n'.join(citations)
    if result['history_truncated']:
        text += '\n\n[本轮仅纳入有限近期上下文]'
    return safe_text(text)


def load(home, sid):
    with core.ConversationStore(home) as store:
        store.clean(sid)
        messages = []
        rows = store.turns(sid)
        for row in rows[-16:]:
            if row['state']:
                state = json.loads(row['state'])
                value = {'status': row['status'], 'error': row['error'],
                         'result': json.loads(row['result']) if row['result'] else None}
                if row['status']=='waiting_permission':
                    value['permission']=state.get('pending_permission')
                messages.append({'question': safe_text(state['question']), 'answer': presentation(value),
                                 'request_id': row['id']})
        return {'thread': sid, 'sources': [], 'mode': core.VERSION, 'messages': messages,
                'last_request': rows[-1]['id'] if rows else None}


def handle(home, request, emit=lambda event: None):
    home = Path(home)
    action, sid = request.get('action'), request.get('thread')
    if action == 'new':
        with core.ConversationStore(home) as store:
            sid = store.create()
        return load(home, sid)
    if action == 'list':
        with core.ConversationStore(home) as store:
            return {'chats': [{**r, 'mode': r['version']} for r in store.sessions()]}
    if action == 'load':
        return load(home, sid)
    if action == 'forget':
        with core.ConversationStore(home) as store:
            store.forget(sid)
        return {'forgotten': True}
    if action == 'budget':
        budget = core.budget_status(home)
        return {'text': f"今日 {budget['daily_tokens']}/{budget['daily_limit']}，本月 {budget['monthly_tokens']}/{budget['monthly_limit']} Token（含预留）",
                'budget': budget}
    if action == 'run':
        from .conversation_tools import submit
        value = submit(home, sid, request.get('query'), turn_id=request.get('request_id'), on_event=emit)
    elif action in ('approve','deny'):
        from .conversation_tools import permission_reply
        value = permission_reply(home,sid,action,request_id=request.get('request_id'),on_event=emit)
    elif action in ('status', 'resume', 'cancel'):
        value = core.inspect(home, sid)
        if value['status'] != 'empty':
            if action == 'resume':
                value = core.send(home, sid, turn_id=value['turn_id'], resume=True, on_event=emit)
            elif action == 'cancel':
                core.cancel(home, sid, value['turn_id'])
                value = core.inspect(home, sid)
    elif action == 'pause':
        return {'thread': sid, 'text': '对话中用Esc中断，再以 /resume 恢复或 /cancel 结束；持续委托暂停仍使用旧工作入口。'}
    else:
        raise ValueError('terminal_unknown_action')
    result = value.get('result') or {}
    total = value.get('new_usage_tokens',result.get('usage_tokens', 0))
    # conversation-v1 stores authoritative total usage; no invented split.
    return {'thread': sid, 'request_id': value.get('turn_id'), 'run_id': value.get('run_id'),
            'status': value['status'], 'text': presentation(value), 'cached': value.get('cached', False),
            'usage': {'total_tokens': total},
            'model_turns': result.get('model_calls'), 'searches': result.get('searches'),
            'failure': {'code': value['error']} if value.get('error') else None}

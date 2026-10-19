"""Small local client of the conversation API, with complete-response output."""
import json
import re
import shutil
import sys

from . import conversation as core
from .runtime_adapter import PI_DIR

HELP = ('/new 新会话  /sessions 会话列表  /open ID 恢复  /history 最近对话\n'
        '/status 状态  /resume 恢复中断轮次  /cancel 取消未完成轮次\n'
        '/approve 确认工具  /deny 拒绝工具  /budget 共享预算  /forget 清除此会话内容  /quit 退出')


def safe_text(value):
    return ''.join(c for c in str(value) if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) <= 159))


def error_text(code):
    if str(code).startswith('model_output_has_invalid_evidence_references:'):
        return '模型回复未通过证据校验，已停止显示；本次计费保留，不自动重试。'
    if str(code).startswith('model_request_not_retryable_') or code == 'model_result_expired_or_revoked_no_retry':
        return '该步骤已有计费或未知结果记录，禁止重新付费执行；已提交结果可用 /status 查看。'
    messages = {
        'empty': '此会话尚无消息。',
        'running': '此轮未完成；若原进程已退出，可用 /resume 显式恢复。',
        'interrupted': '此轮已中断，可用 /resume 恢复已提交步骤，或 /cancel。',
        'cancelled': '此轮已取消。',
        'expired': '此轮已过保留期，正文已清除。',
        'invalidated': '相关来源或历史已失效，正文已清除。',
        'forgotten': '此轮内容已清除，计费和防重标记保留。',
        'chat_interrupted_resume_committed_steps_only': '执行已中断；/resume 仅恢复已提交步骤，未知调用不会重付费。',
        'chat_turn_requires_explicit_resume_or_is_failed': '此轮未完成或已失败；仅安全的中断轮次可用 /resume，失败调用不会自动重做。',
        'chat_invalid_answer_json': '模型未返回约定的JSON格式；本次计费保留，不自动重试。',
        'chat_model_result_unknown_no_retry': '模型结果未知，保留预算预留；不会自动重试。可用 /status 查看。',
        'chat_no_pending_permission': '当前没有待确认的工具动作。',
        'chat_permission_preview_expired': '本次工具确认已过15分钟有效期，未执行；可取消本轮后重新提出请求。',
        'chat_permission_preview_changed': '工具预览已经变化，未执行；请重新查看当前 /status。',
        'chat_invalid_message': '请输入1–512字，凭据类内容不能发送。',
        'chat_session_busy': '此会话正在另一个进程执行，请稍后查看 /status。',
        'chat_previous_turn_unfinished_use_resume_or_cancel': '上一轮尚未完成；请用 /resume 或 /cancel。',
        'chat_context_exceeds_prompt_limit': '上下文达到本轮提示上限；请缩短问题或 /new。未新增本次模型调用。',
        'model_budget_exhausted': '共享模型预算不足，已停止新调用。可用 /budget 查看。',
        'chat_source_or_history_invalidated': '来源已变更或撤权，相关会话内容已失效；请重新检索。',
        'chat_turn_expired_or_invalidated_no_retry': '此轮已过期或失效，不能恢复或重新付费。',
        'chat_model_configuration_disabled_or_changed': '模型未启用或配置已变化；请核对本机PA1配置。',
        'model_provider_cooldown_no_automatic_retry': '模型服务处于冷却期，未自动重试。',
    }
    return messages.get(code, code if re.fullmatch(r'[a-z][a-z0-9_:.-]{0,160}', str(code)) else 'chat_local_configuration_error')


def show(value, output=print):
    if value.get('permission'):
        output('Asis > '+safe_text(value['permission']['prompt']))
        output('回复“同意”或 /approve 执行；回复“不同意”或 /deny 取消。')
        return
    result = value.get('result')
    if result:
        output('Asis > '+safe_text(result['answer']))
        if result.get('uncertainty'):
            output('资料局限：'+safe_text(result['uncertainty']))
        for i, evidence in enumerate(result['evidence'], 1):
            if 'E'+str(i) in result['citations']:
                output(f"[E{i}] "+safe_text(evidence['title'])+' '+safe_text(evidence['original_uri']))
        output(f"[Token {result['usage_tokens']}；检索 {result['searches']}；{'已缓存' if value.get('cached') else '完成'}]")
        if result['history_truncated']:
            output('[仅选择有限近期上下文；更早内容未全部纳入]')
    else:
        output('Asis > '+error_text(value.get('error') or value['status']))


def main(home, *, session=None, continued=False, check=False, list_sessions=False, input_fn=input, output=print):
    if check:
        from . import pa1
        data = pa1.settings(home)
        core.load_pa1_config(home)
        output(json.dumps({'protocol': core.VERSION, 'model': data['model'], 'enabled': data['enabled'],
                           'pi_installed': bool(shutil.which('node') and (PI_DIR/'node_modules/@earendil-works/pi-agent-core').is_dir()),
                           'vps_or_astrbot_required': False, 'streaming_text': False,
                           'model_calls': 0, 'tools': ['search_notes','search_reading','search_web','fetch_web','consult_specialist'],
                           'web_search': 'exact_query_confirmation'}, ensure_ascii=False))
        return 0
    with core.ConversationStore(home) as store:
        sessions = store.sessions()
        if list_sessions:
            for row in sessions:
                output(row['id'])
            return 0
        sid = session or (sessions[0]['id'] if continued and sessions else store.create())
        store.session(sid)
    output('Personal Asis 本机聊天 — '+sid+'\n'+HELP)
    output('MiMo使用既有共享预算；按需检索获准来源，联网先确认具体公开词。')
    if session or continued:
        show(core.inspect(home, sid), output)

    def progress(event):
        if event['phase'] == 'start':
            output('[检索本机资料…]' if event['kind'] == 'tool' else '[模型处理中…]')

    while True:
        try:
            line = input_fn('You > ').strip()
        except (EOFError, KeyboardInterrupt):
            output('\n已退出。恢复：scripts/asis chat --session '+sid)
            return 0
        if not line:
            continue
        try:
            if line in ('/quit', '/exit'):
                output('恢复：scripts/asis chat --session '+sid)
                return 0
            if line == '/help':
                output(HELP)
            elif line == '/new':
                with core.ConversationStore(home) as store:
                    sid = store.create()
                output('会话：'+sid)
            elif line == '/sessions':
                with core.ConversationStore(home) as store:
                    for row in store.sessions():
                        output(row['id'])
            elif line.startswith('/open '):
                candidate = line.split(maxsplit=1)[1]
                with core.ConversationStore(home) as store:
                    store.session(candidate)
                sid = candidate
                show(core.inspect(home, sid), output)
            elif line == '/budget':
                value = core.budget_status(home)
                output(f"今日 {value['daily_tokens']}/{value['daily_limit']}，本月 {value['monthly_tokens']}/{value['monthly_limit']} Token（含预留）；未知调用 {value['unresolved_calls']}")
            elif line == '/history':
                with core.ConversationStore(home) as store:
                    store.clean(sid)
                    for row in store.turns(sid)[-8:]:
                        if row['state'] and row['result']:
                            output('You > '+safe_text(json.loads(row['state'])['question']))
                            output('Asis > '+safe_text(json.loads(row['result'])['answer']))
                        else:
                            output('['+row['status']+'] '+row['id'])
            elif line == '/forget':
                with core.ConversationStore(home) as store:
                    store.forget(sid)
                output('会话内容已清除，计费及防重标记保留。')
            elif line in ('/status', '/resume', '/cancel'):
                value = core.inspect(home, sid)
                if line == '/resume' and value['status'] != 'empty':
                    value = core.send(home, sid, turn_id=value['turn_id'], resume=True, on_event=progress)
                elif line == '/cancel' and value['status'] != 'empty':
                    core.cancel(home, sid, value['turn_id'])
                    value = core.inspect(home, sid)
                show(value, output)
            elif line in ('/approve','/deny'):
                from .conversation_tools import submit
                show(submit(home,sid,line,on_event=progress),output)
            elif line.startswith('/'):
                output(HELP)
            else:
                from .conversation_tools import submit
                value = submit(home, sid, line, on_event=progress)
                show(value, output)
                if value.get('result'):
                    budget = core.budget_status(home)
                    if budget['approaching_limit']:
                        output('[预算提示：日或月额度已使用80%以上；/budget 查看]')
        except (ValueError, OSError) as error:
            output('Asis > '+error_text(str(error)))

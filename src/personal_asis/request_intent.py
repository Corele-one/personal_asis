"""Narrow current-message replies, without implicit access to personal history."""
import json
import re

VERSION='current-message-support-v1'
SYSTEM=(
    '你是用户的个人助手。本次是倾听、安慰或鼓励，只回应用户当前这条消息。'
    '没有读取笔记、日记或历史，不得声称记得过去、引用历史经历、推断原因或诊断用户。'
    '用自然、温和、简短的中文直接回应，尊重用户，不要求其先提供证据或资料，不给永久标签。'
    '不得执行工具或创建任务。只输出四个字段的 JSON：'
    '{"status":"conversational","answer":"给用户的直接回答","citations":[],"uncertainty":""}。'
)

def support_intent(query):
    # A narrow opt-out from retrieval, rather than a general-purpose classifier.
    support=re.search(r'安慰|鼓励|打气|陪我聊|陪我说|听我说|倾听|comfort me|cheer me up',query,re.I)
    grounded=re.search(r'检索|搜索|查找|笔记|日记|记录|资料|历史|以前|之前|复盘|分析|根据|结合|回顾',query)
    return bool(support and not grounded)

def response_plan(query, mode):
    if mode=='conversation' or (mode in ('auto','life') and support_intent(query)):
        return {'version':VERSION,'kind':'conversation','requested_mode':mode,
                'reason':'回应本轮消息；未请求检索历史笔记。','search_notes':False}
    return None

def validate_plan(value, query):
    if value!=response_plan(query,value.get('requested_mode')):
        raise ValueError('agent_response_protocol_changed_no_retry')

def validate_answer(content):
    try:
        value=json.loads(content)
        if (not isinstance(value,dict) or set(value)!={'status','answer','citations','uncertainty'}
                or value['status']!='conversational' or value['citations']!=[]
                or not isinstance(value['answer'],str) or not value['answer'].strip() or len(value['answer'])>1600
                or not isinstance(value['uncertainty'],str) or len(value['uncertainty'])>400
                or re.search(r'\[E[^\]]*\]',value['answer']+value['uncertainty'])):
            raise ValueError()
        return value
    except (ValueError,TypeError):
        raise ValueError('agent_invalid_conversation_response') from None

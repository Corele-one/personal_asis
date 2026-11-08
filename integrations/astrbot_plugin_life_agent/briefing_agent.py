"""Use AstrBot's native Agent with only a bounded read-only briefing tool."""
import asyncio
import json
from types import SimpleNamespace

from .life_briefing import BriefingLibrary, SYSTEM, GENERATION_TIMEOUT, MAX_AGENT_STEPS, provider_failure_meta


async def synthesize(bot, item):
    from astrbot.core.agent.tool import FunctionTool, ToolSet
    from astrbot.api.event import AstrMessageEvent
    from astrbot.core.platform.astrbot_message import AstrBotMessage
    from astrbot.core.platform.platform_metadata import PlatformMetadata

    owner = (bot.config['owner_platform'], bot.config['owner_id'])
    if item['source_owner'] != dict(platform=owner[0], sender=owner[1]):
        raise ValueError('brief_owner_required')

    class BriefEvent(AstrMessageEvent):
        async def send(self, message):
            raise ValueError('brief_agent_has_no_transport')

        def get_sender_name(self):
            return '本人'

        def get_message_outline(self):
            return '[Private briefing]'

    message = AstrBotMessage()
    message.type = 'FriendMessage'
    message.message_id = 'brief-'+item['day']
    message.message = []
    message.sender = SimpleNamespace(user_id=owner[1], nickname='本人')
    event = BriefEvent('整理本期私人简报', message,
        PlatformMetadata(name='private_briefing', description='Read-only briefing',
                         id=owner[0], support_proactive_message=False), item['origin'].split(':', 2)[2])
    if event.unified_msg_origin != item['origin']:
        raise ValueError('brief_private_origin_required')
    library = BriefingLibrary(bot.home, item)

    class ReadLibrary(FunctionTool):
        async def call(self, context, action, source='', query='', key='', offset=0):
            # Recheck policy/ownership/deletions on every read, as well as dispatch.
            if ((bot.config.get('owner_platform'), bot.config.get('owner_id')) != owner
                    or not bot.config.get('capture_enabled', True) or not bot.attention.valid(item)):
                return '{"error":"brief_withdrawn"}'
            return json.dumps(library.query(action, source, query, key, offset), ensure_ascii=False)

    tools = ToolSet([ReadLibrary(name='briefing_library',
        description='Read only the synced Life Journal in this review window and related saved WUCAI/Xiaohongshu text. Search by a short specific topic, then read C keys or initial E keys. Read returns citation E IDs and next_offset for another page; no network, writes, paths or SQL.',
        parameters={'type':'object', 'properties':{
            'action':{'type':'string','enum':['search','read']},
            'source':{'type':'string','enum':['journal','wucai','xiaohongshu']},
            'query':{'type':'string'}, 'key':{'type':'string'},
            'offset':{'type':'integer','minimum':0,'maximum':48000}},
            'required':['action'], 'additionalProperties':False})])
    provider = await bot.context.get_current_chat_provider_id(umo=item['origin'])
    if provider.startswith('asis_router/'):
        provider = 'asis_router/complex'
    answer = await asyncio.wait_for(bot.context.tool_loop_agent(event=event,
        chat_provider_id=provider, system_prompt=SYSTEM,
        prompt=json.dumps(dict(start=item['start'], end=item['end'],
                               coverage=item['coverage'], evidence=item['evidence']), ensure_ascii=False),
        contexts=[], tools=tools, max_steps=MAX_AGENT_STEPS, tool_call_timeout=10,
        request_max_retries=1, fallback_providers=[]),
        timeout=GENERATION_TIMEOUT)
    item['generation_meta'] = dict(role=getattr(answer, 'role', 'assistant'),
        model=getattr(answer,'asis_router_model',''),
        characters=len(answer.completion_text) if isinstance(answer.completion_text, str) else 0,
        tool_calls=len(getattr(answer, 'tools_call_name', []) or []))
    # AstrBot may return provider failures as role=err rather than raise them.
    # They are error receipts, never prose to render or deliver to the owner.
    if getattr(answer, 'role', 'assistant') == 'err':
        item['generation_meta'].update(provider_failure_meta(answer.completion_text))
        raise ValueError('brief_provider_error')
    if getattr(answer, 'tools_call_name', None):
        raise ValueError('brief_agent_incomplete')
    return answer.completion_text

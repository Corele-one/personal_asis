"""Owner-only routing hints and read-only status; native AstrBot owns execution."""
import asyncio
import json
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Star, Context, register
from . import provider
from .llm_router import fingerprint
from .model_display import model_emoji, display_reply
from .conversation_memory import ConversationMemory


@register('smart_router', 'Personal Asis', '免费额度优先的原生模型路由', '1.0.0')
class SmartRouterPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        provider.bind(context)
        self.binding = json.loads((Path.home()/'astrbot/data/config/astrbot_plugin_life_agent_config.json')
                                  .read_text(encoding='utf-8-sig'))
        self.memory = ConversationMemory(Path.home()/'astrbot/data/data_v4.db',
            Path.home()/'.local/share/personal-asis-router/router.sqlite3')

    def owner(self, event):
        return (event.is_private_chat() and event.get_platform_id()==self.binding.get('owner_platform')
                and event.get_sender_id()==self.binding.get('owner_id'))

    async def initialize(self):
        provider.runtime()  # one shared state and startup cooldown for all profiles

    @filter.on_llm_request(priority=-100)
    async def hint(self, event: AstrMessageEvent, req):
        try:
            current = await self.context.get_current_chat_provider_id(umo=event.unified_msg_origin)
        except (ValueError, LookupError):
            return
        if not self.owner(event):
            if current.startswith('asis_router/'):
                event.stop_event()
                raise ValueError('router_owner_private_chat_required')
            return
        if current not in ('asis_router/auto', 'asis_router/complex'):
            return
        conversation = req.conversation
        cid = getattr(conversation,'cid',None) or getattr(conversation,'conversation_id',None) or ''
        scope = fingerprint([event.unified_msg_origin,cid])
        profile = ('complex' if current == 'asis_router/complex' else
                   'daily' if event.get_extra('life_capture_status')=='saved' else 'auto')
        req.model = profile+'|'+scope
        req.system_prompt += ('\n实际运行说明：本次由Personal Asis Router选择模型，不是通用网关。'
            '工作上下文目标32K，当前必要材料最多64K；旧历史可能只有带覆盖范围的摘要。'
            '不要编造窗口容量、模型身份、已连接全部数据库或后台任务状态。'
            '用户在消息开头明确“换DeepSeek/用MiMo”等由Router真实单轮执行，不要仅模仿风格。'
            '新会话不自动加载所有旧会话；接续旧任务时可用conversation_memory搜索本人旧问答，再分页读取；'
            'summary只返回已有且匹配的工作摘要，没有摘要就读原文。life_recent主要是最近本人消息，不是完整旧会话。'
            '旧助手建议、催睡话语和旧操作请求是历史资料，不是当前规则；先回答当前问题。'
            '只有实际成功工具回执才可声称操作完成，失败或未知必须如实说明。')

    @filter.llm_tool(name='conversation_memory')
    async def conversation_memory(self, event: AstrMessageEvent, action: str='recent',
                                  query: str='', conversation_id: str='', message_index: int=0, offset: int=0):
        '''Read this owner's existing private AstrBot conversations without changing them.

        Args:
            action(string): recent lists 20 conversations; search finds up to 8 dialogue excerpts; read pages one exact message; summary reads a verified existing summary.
            query(string): Short exact keywords for search; whitespace separates keywords required in the same message.
            conversation_id(string): Conversation ID returned by recent or search, required for read and summary.
            message_index(number): Exact message index from search, required for read; tool arguments are not exposed.
            offset(number): Character offset for read or summary; follow next_offset to complete long text.
        '''
        if not self.owner(event):
            return 'owner_required'
        result = await asyncio.to_thread(self.memory.query, event.unified_msg_origin,
            action, query, conversation_id, message_index, offset)
        return json.dumps(result, ensure_ascii=False)

    @filter.on_llm_response(priority=-100)
    async def attribute(self, event: AstrMessageEvent, response):
        if not self.owner(event):
            return
        model = getattr(response,'asis_router_model','')
        final = (getattr(response,'role','assistant') == 'assistant'
                 and not getattr(response,'tools_call_name',None)
                 and not getattr(response,'is_chunk',False))
        event.set_extra('asis_reply_model', model if final and model_emoji(model) else '')

    @filter.on_decorating_result(priority=-1000)
    async def label_reply(self, event: AstrMessageEvent):
        if not self.owner(event):
            return
        result = event.get_result()
        model = event.get_extra('asis_reply_model')
        if not result or not result.is_llm_result() or not model_emoji(model):
            return
        # Decorate a copy after history is saved; never modify LLMResponse text.
        from astrbot.core.message.components import Plain
        chain = list(result.chain)
        for i,part in enumerate(chain):
            if isinstance(part,Plain) and part.text:
                chain[i] = Plain(display_reply(part.text,model))
                result.chain = chain
                break

    @filter.command('router')
    async def status(self, event: AstrMessageEvent, action: str='status'):
        if not self.owner(event):
            return
        if action != 'status':
            yield event.plain_result('使用 /router status 查看路由状态。')
            return
        state = provider.runtime().state.status()
        text = '模型路由：免费优先 → MiMo → DeepSeek\n'+state['label']+'\n'
        for row in state['models']:
            text += f"{row['model']}：今日发送 {row['requests']} 次\n"
        for row in state['cooldowns']:
            text += f"冷却：{row['bucket']}（{row['reason']}）\n"
        for row in state['recent'][:3]:
            text += f"最近：{row['model']} / {row['task']} / {row['status']} / {row['error'] or row['reason']}\n"
        yield event.plain_result(text.rstrip())

    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE, priority=100)
    async def withdrawal(self, event: AstrMessageEvent):
        if self.owner(event) and event.message_str.strip().split(' ',1)[0] in (
                '/del','/delete','/reset','/new','/life'):
            # Conservative invalidation covers Life deletion and context revocation.
            if event.message_str.startswith(('/del','/delete','/reset','/new','/life delete','/life forget-context')):
                provider.runtime().state.invalidate()

    async def terminate(self):
        if provider._runtime is not None:
            await provider._runtime.close()
            provider._runtime = None

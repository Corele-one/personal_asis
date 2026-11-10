"""Version-checked Lark integration; never edits AstrBot installation files."""
import asyncio
import json
import re

from astrbot.api import logger
from .chat_ui import ChatUI, display_emoji, reaction_key

class ChatInteraction:
    def __init__(self, bot):
        self.bot = bot
        self.ui = ChatUI(bot.home/'chat-ui.sqlite3', bot.context.conversation_manager)
        self.installed = []
        self.tasks = set()
        self.pending = {}
        self.client = None
        self.platform = None
        self.attach_status = 'not_checked'
        self.confirmations = {}
        self.sweeper = None

    def task(self, coroutine):
        job = asyncio.create_task(coroutine)
        self.tasks.add(job)
        def done(t):
            self.tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.warning('chat_ui operation unavailable; no retry or payload logging')
        job.add_done_callback(done)
        return job

    def install(self):
        if self.installed:
            return True
        import lark_oapi as lark
        platform = self.bot.context.get_platform_inst(self.bot.config['owner_platform'])
        if platform is None or not hasattr(platform,'lark_api'):
            self.attach_status = 'waiting_for_platform'
            return False
        handler = platform.event_handler
        ws = getattr(platform,'client',None)
        if ws is not None and getattr(ws,'_event_handler',None) is not handler:
            self.attach_status = 'dispatcher_identity_mismatch'
            return False
        maps = (getattr(handler,'_callback_processor_map',None),getattr(handler,'_processorMap',None))
        if not all(isinstance(m,dict) for m in maps):
            return False
        extension = (lark.EventDispatcherHandler.builder('','')
            .register_p2_card_action_trigger(self.callback)
            .register_p2_application_bot_menu_v6(self.menu).build())
        for key, processor in extension._callback_processor_map.items():
            if key in handler._callback_processor_map:
                return False
        if any(key in handler._processorMap for key in extension._processorMap):
            return False
        self.client, self.platform = platform.lark_api, platform
        for key, processor in extension._callback_processor_map.items():
            handler._callback_processor_map[key] = processor
            self.installed.append((handler._callback_processor_map,key,processor))
        for key,processor in extension._processorMap.items():
            handler._processorMap[key] = processor
            self.installed.append((handler._processorMap,key,processor))
        self.attach_status = 'attached'
        self.sweeper = asyncio.create_task(self.expirations())
        return True

    async def expirations(self):
        while True:
            await asyncio.sleep(30)
            await self.resolve_pending()

    async def resolve_pending(self):
        now = asyncio.get_running_loop().time()
        for code,event in list(self.confirmations.items()):
            pending = self.bot.calendar_pending.get(code)
            if not pending or pending.get('expires',0)<=now:
                self.confirmations.pop(code,None)
                await self.reaction(event,'done')

    def menu(self, data):
        event = data.event
        operator = getattr(getattr(event,'operator',None),'operator_id',None)
        if getattr(operator,'open_id',None) != self.bot.config['owner_id']:
            return
        key = getattr(event,'event_key','')
        event_id = getattr(getattr(data,'header',None),'event_id','')
        if key not in ('asis_chat_help','asis_chat_sessions','asis_chat_archived') or not event_id:
            return
        if not self.ui.claim_delivery('menu:'+reaction_key(self.bot.config['owner_platform'],event_id)):
            return
        self.task(self.menu_card(key))

    async def menu_card(self, key):
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
        owner = self.bot.config['owner_id']
        origin = self.bot.config['owner_platform']+':FriendMessage:'+owner
        card = await self.view(origin,archived=key=='asis_chat_archived')
        request = CreateMessageRequest.builder().receive_id_type('open_id').request_body(
            CreateMessageRequestBody.builder().receive_id(owner).msg_type('interactive')
            .content(json.dumps(card,ensure_ascii=False)).build()).build()
        response = await asyncio.wait_for(self.client.im.v1.message.acreate(request),5)
        if response.success():
            self.ui.db.execute('INSERT OR REPLACE INTO cards VALUES(?,?)',(response.data.message_id,origin))

    async def view(self, origin, **kwargs):
        await self.resolve_pending()
        now = asyncio.get_running_loop().time()
        count = sum(p.get('origin')==origin and p.get('expires',0)>now for p in self.bot.calendar_pending.values())
        return await self.ui.card(origin,pending_count=count,**kwargs)

    async def close(self):
        if self.sweeper:
            self.sweeper.cancel()
            await asyncio.gather(self.sweeper,return_exceptions=True)
        for mapping,key,processor in self.installed:
            if mapping.get(key) is processor:
                del mapping[key]
        for job in list(self.tasks):
            job.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.ui.close()

    def callback(self, data):
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
        event = data.event
        value = getattr(getattr(event,'action',None),'value',None) or {}
        user = getattr(getattr(event,'operator',None),'open_id',None)
        message_id = getattr(getattr(event,'context',None),'open_message_id',None)
        code = value.get('asis_chat_action','')
        row = self.ui.db.execute('SELECT origin FROM cards WHERE message_id=?',(message_id,)).fetchone()
        token = self.ui.db.execute('SELECT origin FROM actions WHERE token=?',(code,)).fetchone() if isinstance(code,str) else None
        if user != self.bot.config['owner_id'] or not row or not token or row['origin'] != token['origin']:
            return P2CardActionTriggerResponse({'toast':{'type':'error','content':'此卡片不可操作。'}})
        self.task(self.apply_callback(row['origin'],code,message_id))
        return P2CardActionTriggerResponse({'toast':{'type':'info','content':'正在核对会话；结果以卡片更新为准。'}})

    async def apply_callback(self, origin, code, message_id):
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody
        try:
            notice = await self.ui.act(origin,code)
        except Exception:
            notice = '操作结果未知，请发 /chat 核对；不会自动再执行。'
        card = await self.view(origin,notice=notice)
        request = PatchMessageRequest.builder().message_id(message_id).request_body(
            PatchMessageRequestBody.builder().content(json.dumps(card,ensure_ascii=False)).build()).build()
        # Mutations have already been claimed. Never repeat them when patch fails.
        await asyncio.wait_for(self.client.im.v1.message.apatch(request),5)

    async def send_card(self, event, *, archived=False, notice=''):
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody
        card = await self.view(event.unified_msg_origin,archived=archived,notice=notice)
        if not self.installed:
            card['elements'] = [e for e in card['elements'] if e['tag'] != 'action']
        request = ReplyMessageRequest.builder().message_id(str(event.message_obj.message_id)).request_body(
            ReplyMessageRequestBody.builder().msg_type('interactive')
            .content(json.dumps(card,ensure_ascii=False)).build()).build()
        response = await asyncio.wait_for(event.bot.im.v1.message.areply(request),5)
        if not response.success():
            # Explicit server refusal, unlike timeout: a text fallback is safe.
            return False
        mid = response.data.message_id
        self.ui.db.execute('INSERT OR REPLACE INTO cards VALUES(?,?)',(mid,event.unified_msg_origin))
        return True

    async def command(self, event):
        text = event.message_str.strip()
        # AstrBot's command stage may already have consumed the slash.
        raw = getattr(event.message_obj,'message_str',text) or text
        if (text == 'chat' or text.startswith('chat ')) and raw.lstrip().startswith('/chat'):
            text = '/'+text
        if text == 'help':
            text = '/help'
        if text not in ('/', '帮助', '/帮助', '/help', '/chat') and not text.startswith('/chat '):
            return False
        origin = event.unified_msg_origin
        event.stop_event()
        key = reaction_key(event.get_platform_id(),str(event.message_obj.message_id))
        if not self.ui.claim_delivery('command:'+key):
            return True
        notice, archived = '', text == '/chat archived'
        if text == '/chat new' or text.startswith('/chat new '):
            title = text[len('/chat new'):].strip()[:60] or '新话题'
            code = self.ui.token(origin,await self.ui.current(origin),'new',title)
            notice = await self.ui.act(origin,code)
        elif text == '/chat archive':
            cid = await self.ui.current(origin)
            code = self.ui.token(origin,cid,'archive',cid)
            notice = await self.ui.act(origin,code)
        elif re.match(r'^/chat (switch|restore) ',text):
            _,kind,title = text.split(' ',2)
            convs = [c for c in await self.ui.conversations(origin) if c.title == title]
            if len(convs) != 1:
                notice = '会话标题没有唯一匹配，请使用卡片按钮；同名会话可先在原生界面改名。'
            else:
                code = self.ui.token(origin,await self.ui.current(origin),kind,convs[0].cid)
                notice = await self.ui.act(origin,code)
        elif text not in ('/', '帮助', '/帮助', '/help', '/chat', '/chat archived'):
            notice = '使用 /chat、/chat new 标题、/chat switch 完整标题、/chat archive 或 /chat archived。'
        event.stop_event()
        try:
            sent = await self.send_card(event,archived=archived,notice=notice)
            if sent:
                return True
        except Exception:
            logger.warning('chat_ui card delivery unknown; not resending')
            return True
        # No card was accepted; do not fall into normal LLM/capture.
        await event.send(event.plain_result((notice+'\n' if notice else '')+
            'Chat：/chat new 标题 新话题；/chat switch 完整标题 切换；/chat archive 归档当前会话；'
            '/chat archived 查看归档。/router status 查看模型，/life status 查看记录。'))
        return True

    async def reaction(self, event, phase):
        from lark_oapi.api.im.v1 import (CreateMessageReactionRequest, CreateMessageReactionRequestBody,
            DeleteMessageReactionRequest, Emoji)
        key = reaction_key(event.get_platform_id(),str(event.message_obj.message_id))
        client = getattr(event,'bot',None)
        if not client:
            return
        try:
            if phase != 'processing':
                for previous in ('processing','pending'):
                    rid = self.ui.take_reaction(key,previous)
                    if rid:
                        request = DeleteMessageReactionRequest.builder().message_id(str(event.message_obj.message_id)).reaction_id(rid).build()
                        await asyncio.wait_for(client.im.v1.message_reaction.adelete(request),2)
            if phase == 'done' or not self.ui.reserve_reaction(key,phase):
                return
            emoji = {'processing':'Typing','pending':'OneSecond','failed':'CrossMark'}[phase]
            request = CreateMessageReactionRequest.builder().message_id(str(event.message_obj.message_id)).request_body(
                CreateMessageReactionRequestBody.builder().reaction_type(Emoji.builder().emoji_type(emoji).build()).build()).build()
            response = await asyncio.wait_for(client.im.v1.message_reaction.acreate(request),2)
            if response.success() and response.data.reaction_id:
                self.ui.reaction_saved(key,phase,response.data.reaction_id)
        except Exception:
            logger.warning('chat_ui reaction unavailable; main response continues without retry')

    def start(self,event):
        key = reaction_key(event.get_platform_id(),str(event.message_obj.message_id))
        if key in self.pending:
            return
        self.ui.active.setdefault(event.unified_msg_origin,set()).add(key)
        self.pending[key] = self.task(self.reaction(event,'processing'))

    async def finish(self,event):
        key = reaction_key(event.get_platform_id(),str(event.message_obj.message_id))
        job = self.pending.pop(key,None)
        if not job:
            return
        await job
        self.ui.active.get(event.unified_msg_origin,set()).discard(key)
        phase = 'failed' if event.get_extra('chat_ui_failed') else 'done'
        if phase != 'failed' and any(p.get('origin')==event.unified_msg_origin and p.get('expires',0)>asyncio.get_running_loop().time() for p in self.bot.calendar_pending.values()):
            phase = 'pending'
            for code,pending in self.bot.calendar_pending.items():
                if pending.get('origin')==event.unified_msg_origin:
                    self.confirmations[code] = event
        await self.reaction(event,phase)

    async def attributed(self,event,response):
        if getattr(response,'role','') == 'err':
            event.set_extra('chat_ui_failed',True)
        model = getattr(response,'asis_router_model','')
        if model and not getattr(response,'tools_call_name',None) and not getattr(response,'is_chunk',False):
            cid = event.get_extra('chat_ui_cid') or await self.ui.current(event.unified_msg_origin)
            self.ui.attributed(event.unified_msg_origin,cid,model)

    def decorate(self,event):
        result = event.get_result()
        if not result or not result.is_llm_result() or result.async_stream is not None:
            return
        from astrbot.api.message_components import Plain
        chain = list(result.chain)
        for i,part in enumerate(chain):
            if isinstance(part,Plain):
                chain[i] = Plain(display_emoji(part.text))
        result.chain = chain

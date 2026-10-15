"""Only the existing authenticated Feishu transport belongs to this adapter."""

import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody, PatchMessageRequest, PatchMessageRequestBody

sys.path.insert(0, str(Path(os.environ.get("PERSONAL_ASIS_CHECKOUT", "/home/mac/personal-asis")) / "src"))
from personal_asis.feishu import FeishuBridge, summary, view_digest
from personal_asis.coordinator import ProtocolError
from personal_asis.pwa import settings


@register("personal_asis", "Personal Asis", "资料搜索、证据分析与卡片助手", "0.5.0")
class PersonalAsis(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.home = Path(os.environ.get("PERSONAL_ASIS_HOME", "/home/mac/.local/share/personal-asis-coordinator"))
        self.bridge = FeishuBridge(self.home)
        self.worker = None
        self.lock = asyncio.Lock()
        self.card_hooks={}
        self.card_jobs=set()

    def card_store(self):
        from personal_asis.feishu_cards import Cards
        if not hasattr(self,'cards'):
            self.cards=Cards(self.bridge)
        return self.cards

    async def patch_card(self,platform,message,payload):
        request=(PatchMessageRequest.builder().message_id(message).request_body(
            PatchMessageRequestBody.builder().content(json.dumps(payload,ensure_ascii=False)).build()).build())
        response=await self.adapter(platform).lark_api.im.v1.message.apatch(request)
        return response.success()

    async def open_card(self,event):
        from personal_asis.feishu_cards import card
        platform=event.get_platform_id()
        self.install_card_hook(platform)
        store=self.card_store()
        session,fresh=store.create(platform,event.get_sender_id(),event.message_obj.message_id)
        if not fresh:
            return  # A lost send response never causes another card send.
        request=(ReplyMessageRequest.builder().message_id(event.message_obj.message_id).request_body(
            ReplyMessageRequestBody.builder().content(json.dumps(card(session),ensure_ascii=False))
            .msg_type('interactive').uuid(session['id']).reply_in_thread(False).build()).build())
        try:
            response=await self.adapter(platform).lark_api.im.v1.message.areply(request)
            message=getattr(getattr(response,'data',None),'message_id',None) if response.success() else None
            store.sent(session['id'],message)
        except Exception:
            store.sent(session['id'],None)
            raise

    def install_card_hook(self,platform):
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
        adapter=self.adapter(platform)
        hooks=getattr(self,'card_hooks',None)
        if hooks is None:self.card_hooks={};hooks=self.card_hooks
        if platform in hooks:return
        dispatcher=getattr(adapter,'event_handler',None)
        callbacks=getattr(dispatcher,'_callback_processor_map',None)
        if not isinstance(callbacks,dict):raise ValueError('card_callback_adapter_unsupported')
        loop=asyncio.get_running_loop()
        previous=callbacks.get('p2.card.action.trigger')
        def callback(data):
            try:
                action=data.event.action
                value=action.value
                if not isinstance(value,dict) or 'asis_card' not in value:
                    return previous.do(data) if previous else P2CardActionTriggerResponse({})
                if data.header.app_id!=adapter.appid or data.event.host!='im_message':
                    raise ValueError('card_wrong_application')
                store=self.card_store()
                session,job,duplicate=store.accept(platform,data.event.operator.open_id,
                    data.event.context.open_message_id,value,action.form_value)
                if job:
                    # Return the SDK response first; no relay, RSA generation or
                    # model call happens in the synchronous 3-second callback.
                    def schedule():
                        if getattr(self,'card_closed',False):return
                        if not hasattr(self,'card_jobs'):self.card_jobs=set()
                        task=asyncio.create_task(self.process_card(job))
                        self.card_jobs.add(task);task.add_done_callback(self.card_jobs.discard)
                    loop.call_later(.1,schedule)
                from personal_asis.feishu_cards import card
                return P2CardActionTriggerResponse({'toast':{'type':'info','content':
                    '旧操作已处理，请使用当前卡片。' if duplicate else '已接收，正在核对。'},
                    'card':{'type':'raw','data':card(session)}})
            except Exception as error:
                logger.warning('PA card callback error type='+type(error).__name__)
                return P2CardActionTriggerResponse({'toast':{'type':'error',
                    'content':'卡片已过期或操作无效，请重新发送 /asis。'}})
        temporary=lark.EventDispatcherHandler.builder('','').register_p2_card_action_trigger(callback).build()
        processor=temporary._callback_processor_map['p2.card.action.trigger']
        callbacks['p2.card.action.trigger']=processor
        hooks[platform]=(callbacks,processor,previous)

    async def process_card(self,job):
        store=self.card_store()
        try:
            if not hasattr(self,'card_command_lock'):self.card_command_lock=asyncio.Lock()
            async with self.card_command_lock:
                if not self.bridge.authorized(job['platform'],job['owner']):return
                receipt=self.bridge.agent.submit(job['platform'],job['owner'],job['command'],job['action'],
                    target_id=job['target_id'],query=job['query'],source_ids=job['source_ids'],
                    mode=job['mode'],reply_message_id=job['message'],defer_transport=True)
                payload=receipt.pop('transport_payload',None)
                if payload is not None:
                    from personal_asis.agent_channel import relay_control
                    await asyncio.to_thread(relay_control,self.home,{'op':'request',**payload})
                    with self.bridge.db:
                        self.bridge.db.execute('UPDATE agent_routes SET submitted=1 WHERE task_id=?',(receipt['request_id'],))
                store.submitted(job,receipt['request_id'])
        except Exception as error:
            logger.warning('PA card execution error type='+type(error).__name__)
            if store.current_job(job):
                from personal_asis.feishu_cards import card
                try:
                    await self.patch_card(job['platform'],job['message'],card(store.session(job['session']),
                        '指令投递失败或结果未知；请查询原工作编号，不会自动重复付费。'))
                except Exception as patch_error:
                    logger.warning('PA card update error type='+type(patch_error).__name__)

    def adapter(self, platform_id):
        adapter = self.context.get_platform_inst(platform_id)
        if (adapter is None or adapter.meta().name != "lark"
                or adapter.connection_mode != "socket"):
            raise ValueError("authenticated_socket_required")
        return adapter

    async def send(self, platform_id, message_id, text, delivery_id):
        store=self.card_store()
        if store.db.execute('SELECT 1 FROM card_sessions WHERE card_message=?',(message_id,)).fetchone():
            session=store.for_delivery(message_id,delivery_id)
            if session is None:return False
            from personal_asis.feishu_cards import card
            return await self.patch_card(platform_id,message_id,card(session,text))
        adapter = self.adapter(platform_id)
        request = (ReplyMessageRequest.builder().message_id(message_id)
                   .request_body(ReplyMessageRequestBody.builder().content(json.dumps({"text": text}, ensure_ascii=False))
                                 .msg_type("text").uuid(delivery_id).reply_in_thread(False).build()).build())
        response = await adapter.lark_api.im.v1.message.areply(request)
        return response.success()

    async def reply(self, event, text):
        key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"asis-reply:{event.message_obj.message_id}:{text}"))
        await self.send(event.get_platform_id(), event.message_obj.message_id, text, key)

    @filter.regex(r"^/?asis(?:\s|$)", priority=10000)
    async def on_message(self, event: AstrMessageEvent):
        text = event.message_str.strip()
        parts = text.lstrip("/").split(maxsplit=2)
        if not parts or parts[0] != "asis":
            return
        # Reserve the command on every platform. A rejected PA0 command must
        # never fall through into another plugin or the default model pipeline.
        event.should_call_llm(False)
        event.stop_event()
        try:
            platform = event.get_platform_id()
            self.adapter(platform)
            raw = event.message_obj.raw_message
            if (not event.is_private_chat() or getattr(raw, "message_type", None) != "text"
                    or getattr(raw, "parent_id", None)):
                return
            sender = event.get_sender_id()
            action = parts[1] if len(parts) > 1 else "help"
            argument = parts[2] if len(parts) > 2 else ""
            if action in {"bind", "绑定"}:
                if self.bridge.bind(platform, sender, argument):
                    await self.reply(event, "PA0 飞书私聊已绑定。使用 /asis search 关键词；查看进度用 /asis status 任务编号。")
                return
            if not self.bridge.authorized(platform, sender):
                return
            if len(parts)==1 or action in {'menu','菜单','card','卡片'}:
                await self.open_card(event)
            elif action in {"search", "搜索"}:
                task_id = self.bridge.submit(platform, sender, event.message_obj.message_id, argument)
                async with self.lock:
                    for route, view, digest in self.bridge.pending():
                        if route["task_id"] == task_id:
                            await self.bridge.deliver(route, view, digest, self.send)
            elif action in {'agent','助手','agent-status','助手状态','pause','暂停','stop','停止','resume','恢复','cancel','取消'}:
                operation={'agent':'run','助手':'run','agent-status':'status','助手状态':'status',
                           'pause':'pause','暂停':'pause','stop':'pause','停止':'pause',
                           'resume':'resume','恢复':'resume','cancel':'cancel','取消':'cancel'}[action]
                query,sources,target,mode=None,None,None,None
                if operation=='run':
                    source,separator,query=argument.partition('|')
                    if not separator or not source.strip() or not query.strip():
                        await self.reply(event,'用法：/asis agent study research | 问题。角色可选 auto、research、career、life、team；省略角色保留原流程。来源可为 study、life 或 study,life。')
                        return
                    fields=source.split()
                    from personal_asis.agent_roles import MODES
                    if len(fields)>2 or (len(fields)==2 and fields[1] not in MODES):
                        await self.reply(event,'角色请选择 auto、research、career、life 或 team。')
                        return
                    sources=fields[0].split(',')
                    mode=fields[1] if len(fields)==2 else None
                    query=query.strip()
                else:
                    target=argument.strip()
                receipt=self.bridge.agent.submit(platform,sender,event.message_obj.message_id,operation,
                    target_id=target,query=query,source_ids=sources,**({'mode':mode} if mode else {}))
                route={'task_id':str(uuid.uuid5(uuid.NAMESPACE_URL,'asis-agent-ack:'+receipt['request_id'])),
                       'platform_id':platform,'open_id':sender,'message_id':event.message_obj.message_id}
                view={'kind':'agent_receipt','target_id':receipt['target_id'],'submitted':receipt['submitted']}
                async with self.lock:
                    await self.bridge.deliver(route,view,receipt['request_id'],self.send)
            elif action in {'analyze','分析','research','研究'}:
                research=None
                if action in {'research','研究'}:
                    sections=[s.strip() for s in argument.split('|')]
                    if len(sections)<2:
                        await self.reply(event,'用法：/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选，最多3条）')
                        return
                    argument=sections[0]
                    research={'public_query':sections[1],'urls':sections[2:]}
                task_id=self.bridge.submit_analysis(platform,sender,event.message_obj.message_id,argument,research)
                await self.reply(event,f'PA1 已接收：{task_id}。由 Mac 检索获准资料、核对证据并在共享预算内分析，完成后回复此私聊；不会创建任务或日历。')
            elif action in {"status", "状态"}:
                route=self.bridge.db.execute('SELECT * FROM analysis_routes WHERE task_id=? AND platform_id=? AND open_id=?',
                    (argument,platform,sender)).fetchone()
                if route:
                    from personal_asis.analysis_channel import relay_control
                    delivery=self.bridge.db.execute('SELECT state FROM deliveries WHERE task_id=? ORDER BY updated DESC LIMIT 1',(argument,)).fetchone()
                    if delivery:
                        state='delivered' if delivery['state']=='sent' else 'delivery_unknown'
                    else:
                        try:
                            state=relay_control(self.home,{'op':'get','request_id':argument})['status']
                        except ProtocolError:
                            state='expired'
                    labels={'waiting':'等待 Mac 在线','running':'Mac 分析中','ready':'结果已生成，等待此私聊投递','expired':'中转已过期；不会自动重复付费','revoked':'权限已改变，停止展示结果',
                            'delivered':'结果已回复此私聊','delivery_unknown':'通知失败或送达结果未知；不会自动重复发送'}
                    await self.reply(event,f'PA1 {argument}：{labels.get(state,state)}。本机保留计费和防重记录。')
                    return
                view = self.bridge.view(platform, sender, argument)
                uncertain = self.bridge.db.execute("SELECT 1 FROM deliveries WHERE task_id=? AND state IN ('unknown','sending','failed')",
                                                   (argument,)).fetchone()
                prefix = "此前有通知失败或送达结果未知；以下为当前搜索状态。\n" if uncertain else ""
                origin = settings(self.home)["origin"] if (self.home / "pwa.json").exists() else None
                await self.reply(event, prefix + summary(view, origin))
            else:
                await self.reply(event, "搜索：/asis search 关键词；/asis status 搜索编号。分析：/asis analyze 问题。研究：/asis research 私人问题 | 公开检索词 | 公开HTTPS链接。Agent：/asis agent study | 问题（或 life）；/asis agent-status 编号；/asis pause|resume|cancel 编号。")
        except ProtocolError:
            await self.reply(event, "请求无效或任务不属于此账号。使用 /asis search 关键词 或 /asis status 任务编号。")
        except Exception as exc:
            # No query, sender ID, payload, title or path in application logs.
            logger.warning(f"PA0 command error type={type(exc).__name__}")

    @filter.on_astrbot_loaded()
    async def loaded(self):
        row=self.bridge.db.execute('SELECT platform_id FROM binding WHERE singleton=1').fetchone()
        if row and row['platform_id']:
            try:self.install_card_hook(row['platform_id'])
            except Exception as error:logger.warning('PA card adapter unavailable type='+type(error).__name__)
        if self.worker is None:
            self.worker = asyncio.create_task(self.notifications())

    async def notifications(self):
        while True:
            try:
                async with self.lock:
                    for route, view, digest in self.bridge.pending()+self.bridge.pending_analyses()+self.bridge.agent.pending():
                        state = await self.bridge.deliver(route, view, digest, self.send)
                        if view.get('kind')=='analysis':
                            self.bridge.analysis_keys.pop(route['task_id'],None)
                        if view.get('kind')=='agent' and state!='revoked_or_expired':
                            self.bridge.agent.keys.pop(route['task_id'],None)
                        if state in {"failed", "unknown", "sending"}:
                            logger.warning(f"PA0 delivery state={state}")
            except Exception as exc:
                logger.warning(f"PA0 notification error type={type(exc).__name__}")
            await asyncio.sleep(2)

    async def terminate(self):
        self.card_closed=True
        for callbacks,processor,previous in getattr(self,'card_hooks',{}).values():
            if callbacks.get('p2.card.action.trigger') is processor:
                if previous:callbacks['p2.card.action.trigger']=previous
                else:callbacks.pop('p2.card.action.trigger',None)
        for task in getattr(self,'card_jobs',set()):task.cancel()
        if getattr(self,'card_jobs',None):await asyncio.gather(*list(self.card_jobs),return_exceptions=True)
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        self.bridge.close()

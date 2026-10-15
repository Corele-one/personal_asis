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
from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

sys.path.insert(0, str(Path(os.environ.get("PERSONAL_ASIS_CHECKOUT", "/home/mac/personal-asis")) / "src"))
from personal_asis.feishu import FeishuBridge, summary, view_digest
from personal_asis.coordinator import ProtocolError
from personal_asis.pwa import settings


@register("personal_asis", "Personal Asis", "资料搜索与 PA1 证据分析", "0.2.0")
class PersonalAsis(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.home = Path(os.environ.get("PERSONAL_ASIS_HOME", "/home/mac/.local/share/personal-asis-coordinator"))
        self.bridge = FeishuBridge(self.home)
        self.worker = None
        self.lock = asyncio.Lock()

    def adapter(self, platform_id):
        adapter = self.context.get_platform_inst(platform_id)
        if (adapter is None or adapter.meta().name != "lark"
                or adapter.connection_mode != "socket"):
            raise ValueError("authenticated_socket_required")
        return adapter

    async def send(self, platform_id, message_id, text, delivery_id):
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
            if action in {"search", "搜索"}:
                task_id = self.bridge.submit(platform, sender, event.message_obj.message_id, argument)
                async with self.lock:
                    for route, view, digest in self.bridge.pending():
                        if route["task_id"] == task_id:
                            await self.bridge.deliver(route, view, digest, self.send)
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
                await self.reply(event, "搜索：/asis search 关键词；/asis status 搜索编号。分析：/asis analyze 问题。公开研究：/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选）。")
        except ProtocolError:
            await self.reply(event, "请求无效或任务不属于此账号。使用 /asis search 关键词 或 /asis status 任务编号。")
        except Exception as exc:
            # No query, sender ID, payload, title or path in application logs.
            logger.warning(f"PA0 command error type={type(exc).__name__}")

    @filter.on_astrbot_loaded()
    async def loaded(self):
        if self.worker is None:
            self.worker = asyncio.create_task(self.notifications())

    async def notifications(self):
        while True:
            try:
                async with self.lock:
                    for route, view, digest in self.bridge.pending()+self.bridge.pending_analyses():
                        state = await self.bridge.deliver(route, view, digest, self.send)
                        if view.get('kind')=='analysis':
                            self.bridge.analysis_keys.pop(route['task_id'],None)
                        if state in {"failed", "unknown", "sending"}:
                            logger.warning(f"PA0 delivery state={state}")
            except Exception as exc:
                logger.warning(f"PA0 notification error type={type(exc).__name__}")
            await asyncio.sleep(2)

    async def terminate(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass
        self.bridge.close()

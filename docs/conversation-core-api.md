# Conversation Core API 与本机 Web Chat

2026-10-20 范围修订：本 API 当前只服务本机 Pi／CLI／回环 Web。远程 Session 接线、PWA／AstrBot／飞书身份与加密适配全部移至[下一阶段](remote-communications-plan.md)，不作为本机交付条件；下方 P4 描述保留为接口边界参考。本机 Core 不加载旧 Relay，宿主披露检查位于独立 `disclosure.py`。

2026-10-19 checkout 实现 `conversation-session-v1`，由 [ConversationAPI](../src/personal_asis/conversation_api.py) 包装本机 Core。它提供创建／列出 Session、读取有限会话结果、发送一轮、读取步骤事件，以及确认、拒绝、恢复、取消和清除。PWA／AstrBot／飞书适配器可以依赖这个 Core 契约；它们仍须各自验证平台身份、会话归属、内容披露权限和加密投递。

## 本机入口

```sh
scripts/asis web-chat
```

服务只绑定 `127.0.0.1`，端口由系统分配；页面保存当前浏览器标签页的 Session ID，以便刷新恢复。会话列表只显示会话 ID 与最近活动时间，不返回对话预览；可切换会话、新建会话，并显式清除所选会话内容。清理会保留 turn 防重墓碑，不允许再次付费执行相同请求。写操作必须带同源 `Origin`，Host 不匹配或跨源请求会被拒绝。内容只由本机 Conversation Store 提供；旧 VPS PWA 服务没有接入这条本机 HTTP 服务。

对话与 P1 工具确认复用 `conversation_tools.submit`。消息、已验证回答、证据与预算仍归 Core；浏览器是客户端。Session ID 不是远程身份凭据，不能发给另一用户或直接暴露公网。

## 事件与响应

`GET /api/events?id=<session>&after=<sequence>` 返回短连接 SSE。事件有单调序号，重连可用 `Last-Event-ID` 续读。当前事件类型为本轮开始、模型步骤开始／完成、工具步骤开始／完成、等待权限、完成、失败、中断和取消。事件只含工具名、步骤序号、状态或安全错误码，不含用户消息、模型正文、工具返回、证据摘录、路径或凭据。页面可查看待确认动作并继续确认／拒绝，恢复明确可恢复的中断轮次，或取消执行。

MiMo 与现有 Pi Bridge 使用完整响应（`stream:false`）。SSE 只传递已实现的执行状态，页面在本轮完成后读取完整回答；不宣称逐字 Token 流式。下一步需要独立的流式 Model Adapter，在同一预算预留、事件排序、取消和未知结果规则下核验 MiMo 分块行为，不能把完整回答拆成假增量。

## 会话上下文与兼容

会话版本仍是 `conversation-v1`，模型／工具步骤仍按已保存的 `chat-tools-v1` 或历史版本恢复。事件日志30天清理，不替代账本防重状态。来源撤权、内容版本变化和历史依赖仍由 Conversation Store 清理。P2 摘要和较早历史的选择性召回还没有实现；上下文仍按当前四轮／2800 UTF-8字节上限选择。

## 后台委托状态（P3首片）

`scripts/asis proactive preview` 可为既有 Work Delegation 创建待确认策略，明确固定来源、间隔、截止时间、每轮 Token 预算、最大轮数和本机通知条件；`authorize` 要求一次性预览值。可暂停、恢复或取消，状态写入 WorkStore 并留事件；暂停或取消父委托会同步暂停或取消策略，恢复父委托不会自动恢复策略。授权表示用户确认这组规则，不表示调度器已启动。当前没有周期调度执行器、委托预算扣账、完成通知或外部平台通知；活动策略只作为可审计授权记录。

```sh
scripts/asis proactive preview --delegation-id DELEGATION_ID --request-id preview-1 \
  --interval-hours 24 --expires-days 30 --token-budget 2000 --max-runs 4 --notify-when attention
scripts/asis proactive authorize --delegation-id DELEGATION_ID
scripts/asis proactive status --delegation-id DELEGATION_ID
```

预览值只显示一次，下一命令用隐藏输入读取。周期参数只是将来策略边界，不会让该命令启动服务或付费运行。

## P4 渠道状态

本机 Pi、文本 CLI 和本机 Web 共用 Conversation Core。旧 PWA／AstrBot／飞书仍使用各自稳定的旧请求与 Work 协议；本轮没有把它们接到新 Session API，也没有改变服务器。远程接线前必须实现按平台用户绑定 Session、逐来源渠道披露复核、端到端加密事件／回答投递、跨渠道取消与幂等恢复，并分别做本人界面验收。

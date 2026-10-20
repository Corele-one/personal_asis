# 项目文档索引

## 当前入口（2026-10-20）

- [本机 Pi 主线](local-agent-focus.md)：当前范围、依赖方向、本机验收与下一步。
- [本机使用指南](assistant-usage.md)、[完成情况](project-status.md)、[本轮解耦验证](validation/local-agent-isolation-20261020.json)。
- [远程归档清单](archive/remote-communications-20261020.md)、[旧远程用法](archive/remote-usage-20261020.md)、[下一阶段计划](remote-communications-plan.md)。

下方“当前使用与维护”中涉及 VPS／飞书／PWA 的材料均为保留的旧运行资料；远程接线与 P4 暂缓，不构成本机开发或验收前提。线上服务本轮未操作。

当前：[P1持续对话受控工具](conversation-tools-p1.md)记录工具和公开研究门槛；[P2–P4 Core API交付](conversation-core-api.md)说明本机Web Chat、事件SSE、授权策略与尚未接入的远程渠道。`pi`仍是默认入口，本轮checkout续作没有生产部署。

## 本轮入口：Local-first Conversational Agent

- [本地Agent路线与实际架构审计](local-first-agent-roadmap.md)：模块依赖、Conversation与Delegation、Core API、预算／来源／恢复、P0–P4、兼容与回滚。
- [本机Chat使用](assistant-usage.md)：`scripts/asis chat`、恢复、工具状态与当前限制。
- [Conversation Core API](conversation-core-api.md)：本机Web Chat、Session／SSE事件、Proactive Policy与P4渠道适配边界。
- [P2–P4 checkout验证记录](validation/conversation-p2-p4-20261019.json)：当前交付、完整回归数及明确未完成项。
- [本机聊天续作验证](validation/conversation-continuation-20261020.json)：Web 会话切换／清理与当日完整回归；P3/P4未宣称完成。
- [P0验证记录](validation/local-chat-p0-20261019.json)：合成、实际Pi、隔离真实MiMo与旧接口回归分别记录。
- [ADR 0035](adr/0035-prefer-local-conversations-and-opt-in-specialists.md)：默认单主Agent与按需专业能力，修订0022／0025适用范围。

本轮仅checkout实现，不部署或重启服务；下文各日期发布快照保留历史范围，不表示PWA／飞书已经切换新Session协议。

2026-10-19周复盘修复：Mac更新为 `pi-week-review-6e7dc2f9d55e4e11`，VPS保留 `retrieval-context-3fa59e109dd0af73`。修复“过去的一周”的本机时间识别／Life路由、纯文本JSON模式和失败状态空结果处理；日期复盘在原8192字节提示／512生成Token上限内最多选七段。553项回归＝534通过＋19跳过，实际Pi SDK另2项通过；真实Life只读检查覆盖七天，一次MiMo虚构周记生成849 Token并离线复用，人工检查仍发现一处日期归属错误，不能报告为领域质量通过。原失败调用保留且未重试。见[修复说明](pi-weekly-review-fix.md)与[验收记录](validation/pi-weekly-review-20261019.json)。以下为之前发布快照。

2026-10-19本机Pi入口：Mac已发布 `pi-terminal-f35a3859fc4834d1` 的[原生终端界面](pi-terminal.md)，可直接聊天、查看工具过程、保存／恢复本机会话；VPS仍为 `retrieval-context-3fa59e109dd0af73`。新入口复用原MiMo、来源许可、角色与预算，不依赖飞书／VPS，不自动启用v2.3。544项回归＝525通过＋19跳过，另2项实际Pi SDK合成测试通过；真实TTY问候161 Token、无笔记读取，领域质量与完整Retrieval Gate仍待验收。固定启动器及回退材料见[本轮记录](validation/pi-terminal-20261019.json)。以下为前一切片及更早快照。

2026-10-19当前发布 `retrieval-context-3fa59e109dd0af73`：[质量续作](retrieval-context-quality.md)记录日期误筛、词法误报、自然问句与逐字回答实验；532项回归、真实两条回答和[部署验收](validation/retrieval-context-20261019.json)已记录，完整生产替换Gate仍未通过。以下为前一切片及更早记录。

2026-10-19当前发布 `retrieval-quality-e6d8bd41f7ea44a3`：[Retrieval Quality](retrieval-quality.md)记录运行恢复、显式离线重排、冻结题／保留题和私密版本绑定评测；两组合成检索Gate通过，真实探针与完整生产替换未通过，不切换普通检索或旧付费工具。当前测试／发布见[本轮记录](validation/retrieval-quality-20261019.json)。以下10月18日段落保留当时范围。

最新续验：现已发布 `web-live-cfb5d209d8b32103`；公开 DeepSeek→本机正文校验→MiMo引用、Exa真实路径、旧付费恢复与生产加密通道通过；Jina匿名401仍保留降级。新飞书文字入口与501项回归、费用、失败和回退见[真实联网部署](web-search-live-deployment.md)。新能力只在显式公开工作启用，旧角色／私密资料协议与预算不变；以下旧发布及checkout记录保留当时范围。

2026-10-18 新 checkout 切片：[Agent 联网搜索集成](web-search-integration.md)记录 Exa/Jina 适配、新会话工具协议、账户按需正文、证据／权限分派、预算、模拟与真实边界及回退。已实现本机最小闭环，**未部署、未替换默认或已付费 Agent**；飞书新联网工作创建、账户自动分类和披露接线尚待完成。生产发布仍见下节，最新状态见[完成情况](project-status.md)。

## 2026-10-18 Retrieval V2 发布快照

当前发布 `retrieval-v2-de593bc25486b7cc` 已部署Mac／VPS；原解释器、来源／模型许可与普通搜索／Agent协议保持原值。本人飞书私聊测试：`/asis retrieve-v2 study | 缓存一致性`。这是显式词法候选阅读，返回段落与位置，0模型调用；完整质量Gate未过，普通检索未切换。实际协议／测试与回滚见[部署验收](validation/retrieval-v2-deployment-20261018.json)。真实飞书消息和界面由用户自行验证，下列较早发布编号与数量保留历史范围。


2026-10-18：新增 [Retrieval V2](retrieval-v2.md) 审计、39 题基线和独立本机 Chunk／预算上下文实现，**未替换生产 PA1／Agent**。初次基础验收时生产为 `reading-mcp-e181642291535fcc`，随后已按本页顶部续发；当前来源状态按[分层矩阵](information-sources.md)，本轮结果按[验收摘要](validation/retrieval-v2-20261018.json)，历史验收数量不改写。

2026-10-16最新接入：小红书已切换到独立MCP，使用系统钥匙串保存会话与服务鉴权；首页2条、收藏2条、单篇正文、本机搜索和服务重启后会话复用均通过真实验证，缓存共8条（精选2条）。Folo已按用户选择新增arXiv cs.AR＋cs.DC、SIGARCH博客、LLVM发布三条普通订阅，均归“研究与工程”，订阅总数38→41，各读取2条元数据并入本机索引，Folo缓存共9条。Mac发布 `reading-mcp-e181642291535fcc`，395项回归379通过、16跳过；PA0、PA1、独立MCP和隧道运行正常。没有新增模型／远程许可或助手后台抓取；完整历史、完整关注流及平台删除同步未完成。知乎官方CLI停止推进，公众号不接。见[小红书说明](xiaohongshu-setup.md)、[研究信源](source-recommendations.md)和[本轮验收](validation/xhs-mcp-feeds-20261016.json)。

截至 2026-10-16，已部署**基于本机资料的按需助手**，不是完整实施计划的全部交付。PA0 已验收；PA1 检索／分析／按需研究、本人渠道、总管与三个专业角色的串行协作和飞书 `/asis` 卡片已实现。Mac 最新发布为 `reading-mcp-e181642291535fcc`；WUCAI已通过[近期／历史窗口与分页真实读取](validation/wucai-live-20261016.json)，本机缓存24条，未完成整库回溯。Folo已完成[登录及原有时间线验证](validation/folo-live-20261016.json)，现有41项订阅、9条缓存，收藏接口当前返回0；小红书已切换独立MCP，知乎按用户偏好停止推进，公众号按用户要求不再推进。真实卡片／按钮由用户确认，查询与取消有平台成功更新回执。详见[项目完成情况](project-status.md)、[实施计划](implementation-plan.md)、[信源说明](external-reading.md)和[其他信源配置](external-reading-setup.md)。

更完整的连续委托／角色并行、外部来源完整覆盖、持续后台委托／代选、自动长期记忆／规则、正式任务／日历／邮件及饮食照片／作息采集未交付。真实个人多角色分析质量、新版无人值守恢复及整机重启尚未验收。独立备份／恢复密钥暂缓，ROG 停用；各切片历史记录中的版本和待办不覆盖本页当前状态。

## 当前使用与维护

| 文档 | 职责 |
|---|---|
| [Retrieval V2](retrieval-v2.md) | 当前十项检索问题、统一证据、独立 CLI、质量指标、P0/P1/P2 与回滚 |
| [综合助手使用指南](assistant-usage.md) | PWA、飞书卡片、三类问题及当前能力边界 |
| [首批外部阅读信源](external-reading.md) | WUCAI 中国区／Folo 本机配置、只读协议、分页、缓存与完整历史覆盖边界 |
| [外部信源接入与配置记录](external-reading-setup.md) | WUCAI／Folo／独立小红书MCP接入现状、初始准备快照与权限边界 |
| [飞书交互卡片](feishu-cards.md) | `/asis` 表单、异步回调、防重、原卡片更新与真实验证 |
| [回应、检索时间与答案分区](agent-response-routing.md) | 简单倾听不读笔记、相对时间过滤、原文日期与旧工作兼容 |
| [专业角色连续性与目标管理](agent-role-continuity.md) | 各角色独立目标／相关历史、本人 PWA／飞书管理、冻结恢复与失效传播 |
| [总管与专业角色](agent-roles.md) | 串行分工、上下文隔离、共享预算、恢复与质量限制 |
| [Mac 单节点运行](pa0-mac-only.md) | 日常入口、生产 Python、服务与排障顺序 |
| [Mac 本地节点](pa0-mac.md) | 索引行为、来源配置、权限字段与本机服务 |
| [协调服务](pa0-coordinator.md) | 配对、心跳、租约、节点管理与 SSH 出站轮询 |
| [PWA](pa0-pwa.md) | 登录、搜索／正文入口、HTTPS 与服务管理 |
| [飞书](pa0-feishu.md) | 私聊绑定、命令、投递可靠性与渠道限制 |
| [文本阅读与可选能力](pa0-text.md) | 加密阅读协议、格式支持及暂缓的备份能力 |
| [PA1 本机检索与模型分析](pa1-local.md) | 语义模型／缓存、独立私密模型许可、真实联调、MiMo Flash 与预算 |
| [PA1 按需探索验收与使用入口](pa1-acceptance.md) | 本人渠道分析、公开研究、首次真实飞书投递、缓存时延和失败／恢复边界 |
| [委托状态与 Pi 合成适配](agent-runtime-local.md) | 本机委托 CLI、租约／检查点、防重、可选 Pi 1.2.0 验证与尚未上线的范围 |
| [本人 PWA／飞书按需 Agent](agent-channels.md) | 首次检索、跨渠道恢复、飞书收件／投递防重及实际验收 |
| [本机领域目标与约束](agent-domain-context.md) | 明确保存／采用／复核／删除目标，付费会话撤销与隔离；完整领域上下文与角色并行待实现 |
| [相关委托历史检索](agent-work-history.md) | 同领域相关成果、原文与许可核验、固定快照恢复和传递失效 |
| [本人 PWA 按需 Agent](agent-pwa.md) | 加密前台执行、状态、暂停／恢复／取消、控制防重与实际部署验收 |
| [本机按需 Agent 与恢复](agent-on-demand.md) | 实际 MiMo 闭环、持久重建／限次收尾、真实 Study 拒答、共享冷却与 Mac 发布；历史未知预留保留 |

## 验收与设计依据

| 文档 | 职责 |
|---|---|
| [项目完成情况](project-status.md) | 对照实施计划区分已交付、部分完成、未实现与未验收 |
| [PA0 最终验收](pa0-acceptance.md) | 七项条件、测试边界、生产发布及真实休眠证据 |
| [总规格](../SPECIFICATION.md) | 功能、阶段、权限、存储与验收标准 |
| [私人资料与持续授权](private-data-authority.md) | 已确认范围、保留／撤权规则、审批配置和真实落地状态 |
| [领域术语](../CONTEXT.md) | 术语定义；不承载当前部署细节或待办 |
| [项目代理指南](../AGENT.md) | 项目规则正文；AGENTS.md 只维护读取入口 |
| [架构审阅稿](agent-architecture-review.md) | 已确认的 Agent 架构基线 |
| [架构决策](adr/) | 决策及后续范围调整；原决定保留历史上下文 |

## 后续计划

- [实施计划](implementation-plan.md)：PA0 及 PA1 限定按需路径已交付；后续扩大检索质量评估，并按独立门槛推进框架、来源接入及各后续阶段。
- [运行框架验证](agent-runtime-validation.md)：本机状态与 Pi 合成验证已执行；本机 MiMo 闭环及实际来源路径已续验；本人 PWA 的受控 Agent 见 [本轮实现](agent-pwa.md)；本人渠道 Agent 的续建见 [最新记录](agent-channels.md)；通用隔离及持续委托仍待交付。
- [详细架构](agent-architecture.md)、[信息来源](information-sources.md)：未来能力与接入路线。
- [生活与申请需求](personal-development.md)：产品需求和场景，不表示领域能力已上线。

## 历史资料

- [PA0 部署历史](archive/pa0-rollout-2026-10.md)：早期 SSH／防火墙故障、旧来源数量、阶段性测试与部署过程；其中旧待办不代表当前状态。
- [ROG 历史部署](pa0-rog.md)：已停用节点的索引、服务、凭据和验证记录；无需日常维护。
- [原始动机](../Intention.md)、[历史建议](../advice.md)：保留项目背景，当前规则以总规格和最新明确决定为准。

## 维护约定

当前状态回指 PA0 最终验收、PA1 切片记录及[私人资料持续授权](private-data-authority.md)，日常命令放运行文档，后续待办放实施计划，早期过程归档。阶段性数量／版本注明日期；许可由本机配置执行，文档整理不扩大读取、模型或外部写权限。修改后检查相对链接、代码围栏和阶段／权限一致性。

# 调整前 README 快照

2026-10-20 归档；以下为调整前文字，版本、状态与下一步均限原日期，当前主线见[本机 Pi Agent](../local-agent-focus.md)。

# Personal Asis

默认使用本机 Pi 对话：`pi`。还可运行 `scripts/asis chat`（终端文本）或 `scripts/asis web-chat`（仅本机回环 Web Chat）。Web Chat 使用同一 Conversation Core；步骤经 SSE 通知，当前模型回复仍为完整响应。P3 持续授权目前只保存可审计策略，不会自动调度；PWA／AstrBot／飞书尚未接入新 Session API。见[Core API 与 P2–P4状态](../../docs/conversation-core-api.md)。

P1增量（2026-10-19，checkout）：默认Pi对话已接入版本化工具、本机资料与阅读缓存检索、公开搜索／正文读取及确认后的一次专业工作。需要联网时先展示具体公开词，回复“同意”继续同一轮；来源、费用、恢复与限制见[持续对话工具](../../docs/conversation-tools-p1.md)。旧付费协议保留，不启用后台或部署服务。

Personal Asis 的产品目标是 **Local-first、Channel-agnostic、Conversation-first Personal Agent**：在Mac自然持续聊天，由单一主Agent按需选择工具；本机保存资料、会话、权限与预算，多渠道作为适配器。

当前默认用Pi原生界面持续对话，直接启动：

```sh
pi
pi --continue
pi --session 会话ID
pi --check
```

`pi`为本机指向checkout的启动器，仓库入口为`./scripts/asis-pi`；`scripts/asis chat`是共享同一Core的简单文本客户端。普通聊天无需角色／来源／请求编号；支持有限多轮上下文、持久恢复、按需授权本机检索、工具状态、共享预算和付费防重。`/help`查看命令。当前返回完整响应；公开联网先确认具体查询，旧公开研究命令继续可用。新Chat不自动创建长期委托或长期记忆。

本轮未部署生产或重启服务。完整[审计与P0–P4路线](../../docs/local-first-agent-roadmap.md)、[使用方法](../../docs/assistant-usage.md)、[验证记录](../../docs/validation/local-chat-p0-20261019.json)。以下日期段落保留此前发布事实，不作为新Chat验收。

2026-10-19周复盘修复：Mac更新为 `pi-week-review-6e7dc2f9d55e4e11`，VPS保留 `retrieval-context-3fa59e109dd0af73`。修复“过去的一周”的本机时间识别／Life路由、纯文本JSON模式和失败状态空结果处理；日期复盘在原8192字节提示／512生成Token上限内最多选七段。553项回归＝534通过＋19跳过，实际Pi SDK另2项通过；真实Life只读检查覆盖七天，一次MiMo虚构周记生成849 Token并离线复用，人工检查仍发现一处日期归属错误，不能报告为领域质量通过。原失败调用保留且未重试。见[修复说明](../../docs/pi-weekly-review-fix.md)与[验收记录](../../docs/validation/pi-weekly-review-20261019.json)。以下为之前发布快照。

2026-10-19本机Pi入口：Mac已发布 `pi-terminal-f35a3859fc4834d1` 的[原生终端界面](../../docs/pi-terminal.md)，可直接聊天、查看工具过程、保存／恢复本机会话；VPS仍为 `retrieval-context-3fa59e109dd0af73`。新入口复用原MiMo、来源许可、角色与预算，不依赖飞书／VPS，不自动启用v2.3。544项回归＝525通过＋19跳过，另2项实际Pi SDK合成测试通过；真实TTY问候161 Token、无笔记读取，领域质量与完整Retrieval Gate仍待验收。固定启动器及回退材料见[本轮记录](../../docs/validation/pi-terminal-20261019.json)。以下为前一切片及更早快照。

2026-10-19质量续作当前发布 `retrieval-context-3fa59e109dd0af73`：[时间／词法支持与逐字回答](../../docs/retrieval-context-quality.md)已部署到现有Mac／VPS。原16题探针和新增助手自然问句的目标／负例通过；真实两条摘录回答709 Token，原提示和预算上限内运行。完整Gate仍缺真人领域评判、真实缺信息／冲突与新Agent接线；普通入口不切换。验收见[本轮记录](../../docs/validation/retrieval-context-20261019.json)。以下为此前快照。

2026-10-19当前Mac／VPS发布为 `retrieval-quality-e6d8bd41f7ea44a3`：[检索质量实验](../../docs/retrieval-quality.md)新增显式本机重排、独立新Bundle与私密版本绑定评测；隧道和Life索引已恢复。合成检索Gate通过，真实探针与完整生产替换仍未通过；普通检索、权限和历史付费工作不切换。实际验收见[本轮记录](../../docs/validation/retrieval-quality-20261019.json)；下文10月18日为此前发布范围。

**已部署可按需使用的助手，完整实施计划尚未完成。** 2026-10-18当前Mac／VPS发布为 `web-live-cfb5d209d8b32103`：新增显式本人公开检索入口、可选DeepSeek搜索正文与MiMo引用回答，真实调用、失败及501项回归见[联网部署](../../docs/web-search-live-deployment.md)。Jina匿名401仍降级；MiMo模型／预算、普通PA1／角色和历史付费输入不变。WUCAI、Folo、小红书已有本机读取，但账户披露与完整性仍分别检查。逐项状态见[完成情况](../../docs/project-status.md)与[实施计划](../../docs/implementation-plan.md)。

同日最初的[联网 Agent 实验](../../docs/web-search-integration.md)在checkout完成模拟验证；随后已按用户授权进行上述真实续验部署。账户指定条目→V2已有本机入口，完整账户远程抓取／分类／披露链路仍待完成，未新增来源模型／渠道许可。知乎不推进。

本人飞书纯公开测试：`/asis web-deepseek SQLite WAL concurrency site:sqlite.org | 概括取得的页面并引用，说明来源和片段局限。` 不读取个人笔记；新命令保留结果与用量，恢复原工作不会重新付费。真实消息／手机UI由用户验收。

PA0 已按 Mac 单节点范围验收；VPS 负责协调和渠道入口，ROG 停用。2026-10-14 验收时索引 Study 267 篇、Life 181 篇，共 448 篇 Markdown；这不是实时来源数量。独立备份和恢复密钥按用户选择暂缓，整机重启未验。

## 使用入口

Mac直接使用：运行 `./scripts/asis-pi`，或在Finder双击 `scripts/Personal Asis.command`。恢复最近聊天用 `--continue`；详见[本机Pi](../../docs/pi-terminal.md)。界面与工具在Mac，模型沿用MiMo Flash。

V2 只读实验：本人已绑定飞书私聊发送 `/asis retrieve-v2 study | 缓存一致性`。返回候选段落、来源与位置，不调用模型。部署与验证见[续发记录](../../docs/validation/retrieval-v2-deployment-20261018.json)。

- 本人 Miyuki 私聊发送 **`/asis`**：打开交互卡片，选择角色／资料范围、提交问题、查询进度、暂停／恢复／取消。原卡片入口和按钮已由用户确认，新目标管理排版待真人复核。
- [私有 PWA](https://35.209.202.207/)：搜索、加密阅读、「结合资料分析」／「按需公开研究」及「个人助手」角色选择。
- 原文字命令保留：`/asis search 关键词`、`/asis analyze 问题`、`/asis research 私人问题 | 公开检索词 | 公开HTTPS链接（可选）`。
- 既有工作使用原编号查询或明确恢复；已付费步骤免费复用，结果未知时不自动重做。Mac 必须在线才能读取正文和分析；当前没有自动后台委托。

来源原文保留原位置。Study／Life 按[持续授权](../../docs/private-data-authority.md)覆盖现有与新增文件，包括日记和健康资料；凭据和显式排除项优先，模型只处理问题相关的最小上下文。正文阅读、模型处理和渠道展示分别检查权限。

外部来源完整历史／关注流、平台删除同步与自动增量尚未完成，现有外部缓存没有模型或远程正文披露许可。持续委托／自动代选、自动长期记忆／规则、正式任务／日历／邮件，以及照片／作息采集尚未实现。已有领域目标／短期工作历史不等于 PA4 长期记忆，委托状态也不等于 PA2 正式行动任务。新版无人值守恢复、完整 PWA 人工操作和真实个人多角色分析质量仍待验收。使用与限制见[综合指南](../../docs/assistant-usage.md)。

## 文档入口

| 需要了解的内容 | 文档 |
|---|---|
| 检索架构审计、独立 V2 与质量门槛 | [Retrieval V2](../../docs/retrieval-v2.md) |
| 新版 Agent 联网工具、账户正文、隐私／预算与回退 | [联网集成](../../docs/web-search-integration.md) |
| 真实Exa／DeepSeek／MiMo、Jina限制与当前部署 | [真实联网续验](../../docs/web-search-live-deployment.md) |
| 当前完成情况与缺口 | [项目完成情况](../../docs/project-status.md) |
| 综合助手／飞书卡片 | [使用指南](../../docs/assistant-usage.md)、[卡片说明](../../docs/feishu-cards.md) |
| 完整文档导航 | [文档索引](../../docs/README.md) |
| 当前日常运行与排障 | [Mac 单节点运行](../../docs/pa0-mac-only.md) |
| PA0 是否通过及验证依据 | [最终验收](../../docs/pa0-acceptance.md) |
| PA1 入口、研究与验收 | [按需探索验收](../../docs/pa1-acceptance.md)；[本机检索与模型分析](../../docs/pa1-local.md) |
| 配置、权限、协议与阅读 | [Mac](../../docs/pa0-mac.md)、[协调](../../docs/pa0-coordinator.md)、[PWA](../../docs/pa0-pwa.md)、[飞书](../../docs/pa0-feishu.md)、[文本阅读](../../docs/pa0-text.md) |
| 后续交付顺序 | [实施计划](../../docs/implementation-plan.md) |
| 项目规则与规格 | [AGENT.md](../../AGENT.md)、[SPECIFICATION.md](../../SPECIFICATION.md)、[CONTEXT.md](../../CONTEXT.md) |

## 本机命令与开发验证

在仓库根目录执行，输出 JSON：

```sh
scripts/asis doctor
scripts/asis status
scripts/asis search "芯片" --limit 5
scripts/asis reconcile
scripts/asis audit
scripts/asis-pa1 retrieve --source study --query "共享内存副本如何保持一致"
scripts/asis retrieval-v2 search --source study --query "缓存一致性" --mode lexical --diagnostics-only
scripts/asis-pa1 budget
scripts/asis work list
scripts/asis agent validate  # 可选 Pi 依赖安装后，仅使用合成资料
```

仓库入口默认使用 `python3`。生产 Mac 使用私密运行目录中的 Python 环境及发布包；可选依赖和维护方法见 [运行说明](../../docs/pa0-mac-only.md)，不要用缺少加密依赖的基础解释器覆盖生产服务。

核心要求 Python 3.11+、SQLite 3.34+ 与 FTS5 trigram；PDF／Office 和加密能力按需使用 [可选依赖](../../pyproject.toml)。本机运行数据位于 `~/Library/Application Support/PersonalAsis/`，配置、索引、日志与凭据均不进入 Git。

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

测试使用合成资料；可选依赖缺失时明确跳过，不把跳过计为通过。历史部署、旧测试来源和停用 ROG 的记录见 [部署归档](../../docs/archive/pa0-rollout-2026-10.md) 与 [ROG 历史](../../docs/pa0-rog.md)。
